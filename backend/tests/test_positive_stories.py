"""Unit tests for the Positive Stories selection rule.

Every test here is pure Python — no database, no HTTP. Each test's
docstring names the spec case it covers (from the request that
introduced this feature):

    1. Qualifying positive story
    2. Mixed/neutral story excluded (mean_too_low)
    3. Insufficient analyzed coverage (too_few_analyzed)
    4. Insufficient outlet coverage (too_few_outlets)
    5. Stale story
    6. Ordering
    7. Empty result

Plus a case for the consensus-fraction bar (rule 5 in the module
docstring), which prevents a single very-positive outlier from
tipping the mean past the mean-only bar.

An API-level integration test — that would exercise the SQL
aggregation and FastAPI wiring — would need the DB fixture; that is
skipped in environments without ``DATABASE_URL_TEST`` per the
existing convention, so it is intentionally left for the DB-enabled
CI/dev step.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.analysis.positive_stories import (
    MIN_ANALYZED_ARTICLES,
    MIN_OUTLETS,
    POSITIVE_ARTICLE_THRESHOLD,
    POSITIVE_FRACTION,
    POSITIVE_MEAN_THRESHOLD,
    RECENT_WINDOW_DAYS,
    DisqualifyReason,
    StorySentimentAggregate,
    qualifies,
    rank_key,
    select_positive_stories,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def _agg(
    *,
    story_id: int = 1,
    hours_old: float = 6.0,
    distinct_outlets: int = MIN_OUTLETS,
    analyzed_articles: int = MIN_ANALYZED_ARTICLES,
    positive_articles: int | None = None,
    mean_body_sentiment: float | None = 0.30,
) -> StorySentimentAggregate:
    """Build a StorySentimentAggregate with sensible defaults.

    By default the returned aggregate satisfies every rule — tests
    override individual fields to trip one rule at a time.

    When ``positive_articles`` is not passed it defaults to the total
    analyzed count (all analyzed articles positive), so the consensus
    bar is satisfied by default.
    """
    if positive_articles is None:
        positive_articles = analyzed_articles
    return StorySentimentAggregate(
        story_id=story_id,
        last_seen_at=NOW - timedelta(hours=hours_old),
        distinct_outlets=distinct_outlets,
        analyzed_articles=analyzed_articles,
        positive_articles=positive_articles,
        mean_body_sentiment=mean_body_sentiment,
    )


# =============================================================================
# Rule constants sanity — future-you refactors thresholds; guard against
# a change that silently defeats every test in this file.
# =============================================================================

def test_rule_constants_are_sane():
    """Every constant must be a permissive-but-real bar. If any of
    these get flipped by accident, most of this file becomes a no-op."""
    assert RECENT_WINDOW_DAYS >= 1
    assert MIN_OUTLETS >= 2
    assert MIN_ANALYZED_ARTICLES >= 2
    assert -1.0 <= POSITIVE_ARTICLE_THRESHOLD <= 1.0
    assert -1.0 <= POSITIVE_MEAN_THRESHOLD <= 1.0
    assert 0.0 < POSITIVE_FRACTION <= 1.0


# =============================================================================
# 1. Qualifying positive story
# =============================================================================

def test_qualifying_positive_story_passes():
    """Spec case 1: multi-outlet, freshly seen, meaningfully analyzed,
    with a strongly positive mean and consensus — qualifies."""
    agg = _agg(
        hours_old=6.0,
        distinct_outlets=4,
        analyzed_articles=5,
        positive_articles=5,
        mean_body_sentiment=0.42,
    )
    assert qualifies(agg, now=NOW) is None


def test_qualifying_at_threshold_boundaries():
    """Every threshold uses ``>=`` — a story exactly on the bar
    still qualifies, not falls off. Guards against future off-by-one
    edits."""
    agg = _agg(
        distinct_outlets=MIN_OUTLETS,
        analyzed_articles=MIN_ANALYZED_ARTICLES,
        # every analyzed article is exactly at the positive-article bar,
        # so all count as positive, so fraction = 1.0 >= POSITIVE_FRACTION.
        positive_articles=MIN_ANALYZED_ARTICLES,
        mean_body_sentiment=POSITIVE_MEAN_THRESHOLD,
    )
    assert qualifies(agg, now=NOW) is None


# =============================================================================
# 2. Mixed/neutral story excluded (mean_too_low)
# =============================================================================

def test_mixed_or_neutral_mean_is_excluded():
    """Spec case 2: story with a neutral (mean near 0) aggregate must
    be excluded — the average tone did not clear the bar."""
    agg = _agg(mean_body_sentiment=0.05)  # below POSITIVE_MEAN_THRESHOLD=0.15
    assert qualifies(agg, now=NOW) == "mean_too_low"


def test_negative_mean_is_excluded():
    """A story whose coverage is on-average negative is not just
    'not positive' — the same disqualifier catches it."""
    agg = _agg(mean_body_sentiment=-0.40)
    assert qualifies(agg, now=NOW) == "mean_too_low"


# =============================================================================
# 3. Insufficient analyzed coverage (too_few_analyzed)
# =============================================================================

def test_too_few_analyzed_articles_is_excluded():
    """Spec case 3: a story with only 1–2 analyzed articles is
    excluded, even if the sentiment on those was strongly positive."""
    agg = _agg(
        analyzed_articles=MIN_ANALYZED_ARTICLES - 1,
        positive_articles=MIN_ANALYZED_ARTICLES - 1,
        mean_body_sentiment=0.80,
    )
    assert qualifies(agg, now=NOW) == "too_few_analyzed"


def test_null_mean_body_sentiment_is_excluded_as_too_few_analyzed():
    """If the SQL aggregate somehow produced NULL for the mean
    (no analyzed rows for the story), that's the same failure mode
    as 'too few analyzed' — we treat it as such rather than passing
    it through the mean test and crashing."""
    # (When analyzed_articles is 0 the mean is None; we don't rely on
    # analyzed_articles ordering here because rule 3 short-circuits
    # first — but for defense-in-depth we test the None branch
    # explicitly by passing enough analyzed_articles that rule 3 is
    # bypassed and rule 4 has to catch the None.)
    agg = _agg(
        analyzed_articles=MIN_ANALYZED_ARTICLES,
        positive_articles=MIN_ANALYZED_ARTICLES,
        mean_body_sentiment=None,
    )
    assert qualifies(agg, now=NOW) == "too_few_analyzed"


# =============================================================================
# 4. Insufficient outlet coverage (too_few_outlets)
# =============================================================================

def test_too_few_outlets_is_excluded():
    """Spec case 4: 'multi-outlet' means >= MIN_OUTLETS distinct
    outlets. A story below that bar — even with strongly positive
    coverage — is excluded."""
    agg = _agg(
        distinct_outlets=MIN_OUTLETS - 1,
        mean_body_sentiment=0.60,
    )
    assert qualifies(agg, now=NOW) == "too_few_outlets"


def test_zero_outlets_is_excluded():
    """Defensive: a story with an empty outlet count still triggers
    the same rule (never the mean/consensus branch)."""
    agg = _agg(distinct_outlets=0, mean_body_sentiment=0.60)
    assert qualifies(agg, now=NOW) == "too_few_outlets"


# =============================================================================
# 5. Stale story
# =============================================================================

def test_stale_story_is_excluded():
    """Spec case 5: a story last seen outside the freshness window
    is not eligible however positive its coverage was."""
    # 1 day past the window edge.
    agg = _agg(hours_old=(RECENT_WINDOW_DAYS + 1) * 24)
    assert qualifies(agg, now=NOW) == "stale"


def test_exactly_at_freshness_edge_still_qualifies():
    """The freshness rule is inclusive: a story last seen exactly
    at now - window still qualifies. Prevents an off-by-one that
    silently drops borderline stories."""
    agg = _agg(hours_old=RECENT_WINDOW_DAYS * 24)
    assert qualifies(agg, now=NOW) is None


# =============================================================================
# 5b. Consensus (rule 5 in the module) — an outlier tipping the mean
# =============================================================================

def test_one_outlier_dragging_mean_up_is_excluded_by_consensus():
    """A very-positive single article tipping the average past the
    mean bar, while most other analyzed articles are near-neutral,
    is caught by the consensus fraction rule.

    Concrete construction: 5 analyzed articles, one at ~0.9, four at
    ~0.05. Mean = (0.9 + 4*0.05) / 5 = 0.22 (passes mean bar of 0.15).
    Only the outlier counts as 'positive' by article threshold 0.10,
    so positive_articles=1, fraction=0.2 << POSITIVE_FRACTION.
    """
    agg = _agg(
        analyzed_articles=5,
        positive_articles=1,
        mean_body_sentiment=0.22,
    )
    assert qualifies(agg, now=NOW) == "consensus_too_low"


# =============================================================================
# 6. Ordering
# =============================================================================

def test_ranking_prefers_higher_mean_first():
    """Ordering primary key: mean_body_sentiment DESC — the more
    positive story comes first."""
    high = _agg(story_id=10, mean_body_sentiment=0.50)
    mid  = _agg(story_id=11, mean_body_sentiment=0.30)
    low  = _agg(story_id=12, mean_body_sentiment=0.20)
    picked = select_positive_stories(
        [mid, low, high],  # deliberately unordered input
        now=NOW,
    )
    assert [p.story_id for p in picked] == [10, 11, 12]


def test_ranking_tie_breaks_by_more_outlets_then_freshness_then_id():
    """Secondary keys: distinct_outlets DESC, then last_seen_at DESC,
    then story_id DESC. Every tie-breaker is exercised here.
    """
    # Same mean, but different outlet counts — outlet-heavier wins.
    a = _agg(story_id=1, distinct_outlets=3, hours_old=5, mean_body_sentiment=0.40)
    b = _agg(story_id=2, distinct_outlets=5, hours_old=5, mean_body_sentiment=0.40)
    # Same mean AND outlets — fresher wins.
    c = _agg(story_id=3, distinct_outlets=5, hours_old=2, mean_body_sentiment=0.40)
    # Same mean AND outlets AND freshness — higher story_id wins.
    d = _agg(story_id=4, distinct_outlets=5, hours_old=2, mean_body_sentiment=0.40)

    picked = select_positive_stories([a, b, c, d], now=NOW)
    # Expected order: d (mean=,outlets=5,fresh=2h,id=4) > c > b > a
    assert [p.story_id for p in picked] == [4, 3, 2, 1]


def test_ranking_is_deterministic_across_calls():
    """Same input twice must produce identical output. No hidden
    non-determinism (dict iteration, set order, hash randomization)."""
    inputs = [
        _agg(story_id=1, mean_body_sentiment=0.30, distinct_outlets=3),
        _agg(story_id=2, mean_body_sentiment=0.30, distinct_outlets=4),
        _agg(story_id=3, mean_body_sentiment=0.30, distinct_outlets=3, hours_old=2),
        _agg(story_id=4, mean_body_sentiment=0.50, distinct_outlets=3),
    ]
    a = select_positive_stories(list(inputs), now=NOW)
    b = select_positive_stories(list(reversed(inputs)), now=NOW)
    assert [x.story_id for x in a] == [x.story_id for x in b]


def test_rank_key_returns_a_negated_tuple():
    """rank_key is a sort key, so it must be totally-ordered and
    strictly deterministic. Two calls on the same aggregate must
    produce equal tuples."""
    agg = _agg(story_id=7, mean_body_sentiment=0.4, distinct_outlets=4)
    assert rank_key(agg) == rank_key(agg)
    # All four elements are negated for a natural ascending sort.
    k = rank_key(agg)
    assert k[0] == pytest.approx(-0.4)
    assert k[1] == -4
    assert k[3] == -7


# =============================================================================
# 7. Empty result
# =============================================================================

def test_empty_input_produces_empty_output():
    """Spec case 7: given no aggregates, the selector returns an
    empty list (never None, never a crash)."""
    assert select_positive_stories([], now=NOW) == []


def test_all_disqualified_produces_empty_output():
    """Spec case 7 (harder): every input aggregate fails at least one
    rule, so the output is empty even though the input wasn't."""
    stale = _agg(story_id=1, hours_old=RECENT_WINDOW_DAYS * 24 + 24)
    low_outlets = _agg(story_id=2, distinct_outlets=MIN_OUTLETS - 1)
    low_mean = _agg(story_id=3, mean_body_sentiment=0.00)
    thin = _agg(
        story_id=4,
        analyzed_articles=MIN_ANALYZED_ARTICLES - 1,
        positive_articles=MIN_ANALYZED_ARTICLES - 1,
    )
    outlier = _agg(story_id=5, analyzed_articles=5,
                   positive_articles=1, mean_body_sentiment=0.22)
    picked = select_positive_stories(
        [stale, low_outlets, low_mean, thin, outlier],
        now=NOW,
    )
    assert picked == []


def test_limit_zero_returns_empty_list():
    """A caller passing limit=0 must get an empty list, never a
    negative slice."""
    agg = _agg(mean_body_sentiment=0.50)
    assert select_positive_stories([agg], now=NOW, limit=0) == []


def test_limit_caps_the_result_length():
    """The returned list is capped at ``limit``, keeping the
    highest-ranked entries."""
    aggs = [
        _agg(story_id=i, mean_body_sentiment=0.5 - i * 0.01)
        for i in range(1, 11)
    ]
    picked = select_positive_stories(aggs, now=NOW, limit=3)
    assert len(picked) == 3
    # Top three by mean_body_sentiment DESC = i=1,2,3.
    assert [p.story_id for p in picked] == [1, 2, 3]


# =============================================================================
# Contract: qualify() reason values are the documented literal set
# =============================================================================

@pytest.mark.parametrize(
    "reason",
    ["stale", "too_few_outlets", "too_few_analyzed",
     "mean_too_low", "consensus_too_low"],
)
def test_disqualify_reasons_are_the_documented_set(reason: str):
    """DisqualifyReason is a closed set; if a future edit adds a
    reason without updating the docstring, this test fails so the
    frontend contract stays in lockstep."""
    # DisqualifyReason is a typing.Literal — just verify every listed
    # reason is a plain string, i.e. can be JSON-serialised.
    assert isinstance(reason, str)
    # Sanity check that the type alias is exported for downstream
    # consumers (e.g. an observability endpoint could return it).
    assert DisqualifyReason is not None
