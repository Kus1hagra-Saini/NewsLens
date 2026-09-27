"""Positive Stories — deterministic selection rule.

"Positive Stories" describes stories whose CROSS-OUTLET COVERAGE is
predominantly positive/constructive in tone. It is a description of
the sentiment of the coverage, NOT a claim that any real-world event
is "good news".

Uses only data NewsLens already stores:
  * ``stories.last_seen_at``      — freshness
  * ``articles.outlet_id``         — distinct-outlet count per story
  * ``article_analysis.body_sentiment`` — per-article sentiment

Nothing here calls an LLM, adds a table, or introduces a new model.
The qualification is a pure function of the numeric aggregate below,
which the API route computes in SQL.

Rule (all conditions must hold):

  1. Freshness: last_seen_at >= now() - RECENT_WINDOW_DAYS
  2. Multi-outlet: distinct outlets covering the story >= MIN_OUTLETS
  3. Meaningful analysis: analyzed-article count with a non-null
     body_sentiment >= MIN_ANALYZED_ARTICLES
  4. Mean tone is positive:
     mean(body_sentiment) >= POSITIVE_MEAN_THRESHOLD
  5. Consensus positive:
     fraction of analyzed articles with
     body_sentiment >= POSITIVE_ARTICLE_THRESHOLD
     is at least POSITIVE_FRACTION

Rules 4 and 5 together mean "the coverage was mostly positive AND not
just because one very positive outlier dragged the mean up".

Ordering for the returned list (deterministic, no ties by design):
  a. mean_sentiment DESC        (most positive first)
  b. distinct_outlets DESC      (broader consensus above narrower)
  c. last_seen_at DESC          (fresher first)
  d. story_id DESC              (final tie-breaker)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Literal


# ---------------------------------------------------------------------------
# Rule constants — every threshold in one place so the rule is auditable.
# ---------------------------------------------------------------------------

RECENT_WINDOW_DAYS: int = 7
MIN_OUTLETS: int = 3
MIN_ANALYZED_ARTICLES: int = 3

# The average-tone bar. A story's mean body_sentiment must reach this.
POSITIVE_MEAN_THRESHOLD: float = 0.15

# The per-article bar used to count "positive" articles inside a story.
POSITIVE_ARTICLE_THRESHOLD: float = 0.10

# The consensus bar: at least this fraction of analyzed articles must be
# individually positive by POSITIVE_ARTICLE_THRESHOLD.
POSITIVE_FRACTION: float = 0.60

# Default cap for the API's ``limit`` query param.
DEFAULT_LIMIT: int = 12
MAX_LIMIT: int = 40


# ---------------------------------------------------------------------------
# Aggregate — one row per story, produced by the API route from a single
# SQL GROUP BY. Kept as a plain dataclass so unit tests don't need a DB.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StorySentimentAggregate:
    """The numeric summary the selection rule operates on.

    All fields are computed from data that already exists:
      * ``distinct_outlets`` — ``COUNT(DISTINCT outlet_id)`` for the story
      * ``analyzed_articles`` — count of articles with a non-null
        ``article_analysis.body_sentiment`` (i.e. articles that reached
        the ``analyzed`` state and produced a numeric sentiment).
      * ``mean_body_sentiment`` — ``AVG(body_sentiment)`` across those
        analyzed articles.
      * ``positive_articles`` — count of those analyzed articles whose
        individual body_sentiment >= POSITIVE_ARTICLE_THRESHOLD.
      * ``last_seen_at`` — the story's freshness timestamp.
    """
    story_id: int
    last_seen_at: datetime
    distinct_outlets: int
    analyzed_articles: int
    positive_articles: int
    mean_body_sentiment: float | None


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------

DisqualifyReason = Literal[
    "stale",
    "too_few_outlets",
    "too_few_analyzed",
    "mean_too_low",
    "consensus_too_low",
]


def qualifies(
    agg: StorySentimentAggregate,
    *,
    now: datetime,
    window_days: int = RECENT_WINDOW_DAYS,
    min_outlets: int = MIN_OUTLETS,
    min_analyzed: int = MIN_ANALYZED_ARTICLES,
    positive_mean: float = POSITIVE_MEAN_THRESHOLD,
    positive_article: float = POSITIVE_ARTICLE_THRESHOLD,
    positive_fraction: float = POSITIVE_FRACTION,
) -> DisqualifyReason | None:
    """Return None when the story qualifies, otherwise the reason it
    was excluded. Every threshold is a parameter so tests can pin the
    exact rule and future callers can experiment without touching the
    module constants.

    ``positive_article`` isn't checked here — it defines what counts
    as a "positive" article, which the caller has already applied when
    computing ``agg.positive_articles``. We accept it as a parameter so
    the API route + the tests can pass it through explicitly and stay
    in sync with whatever the SQL uses.
    """
    # 1. freshness
    age_s = (now - agg.last_seen_at).total_seconds()
    if age_s > window_days * 86400.0:
        return "stale"

    # 2. multi-outlet
    if agg.distinct_outlets < min_outlets:
        return "too_few_outlets"

    # 3. meaningful analysis coverage
    if agg.analyzed_articles < min_analyzed:
        return "too_few_analyzed"

    # 4. mean tone positive
    if agg.mean_body_sentiment is None:
        return "too_few_analyzed"
    if agg.mean_body_sentiment < positive_mean:
        return "mean_too_low"

    # 5. consensus positive
    fraction = (
        agg.positive_articles / agg.analyzed_articles
        if agg.analyzed_articles > 0
        else 0.0
    )
    if fraction < positive_fraction:
        return "consensus_too_low"

    # No mention of `positive_article` here — see the docstring; the
    # threshold shapes how ``positive_articles`` was counted upstream.
    del positive_article

    return None


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

def rank_key(agg: StorySentimentAggregate) -> tuple:
    """Sort key for qualifying stories (highest-ranked first).

    The tuple is negated so the natural ``sorted(reverse=False)``
    ascending sort puts the top-ranked story first. Fully deterministic
    for any input set — ties break on story_id so the same input always
    produces the same order.
    """
    return (
        -(agg.mean_body_sentiment or 0.0),
        -agg.distinct_outlets,
        -agg.last_seen_at.timestamp(),
        -agg.story_id,
    )


def select_positive_stories(
    aggregates: Iterable[StorySentimentAggregate],
    *,
    now: datetime,
    limit: int = DEFAULT_LIMIT,
    window_days: int = RECENT_WINDOW_DAYS,
    min_outlets: int = MIN_OUTLETS,
    min_analyzed: int = MIN_ANALYZED_ARTICLES,
    positive_mean: float = POSITIVE_MEAN_THRESHOLD,
    positive_article: float = POSITIVE_ARTICLE_THRESHOLD,
    positive_fraction: float = POSITIVE_FRACTION,
) -> list[StorySentimentAggregate]:
    """Filter to qualifying stories, sort by rank_key, cap at limit.

    All thresholds forwarded to :func:`qualifies` are exposed here too
    so the API route can pass the same values it used in SQL, keeping
    the Python selection and the SQL aggregation in lockstep.
    """
    kept = [
        a for a in aggregates
        if qualifies(
            a,
            now=now,
            window_days=window_days,
            min_outlets=min_outlets,
            min_analyzed=min_analyzed,
            positive_mean=positive_mean,
            positive_article=positive_article,
            positive_fraction=positive_fraction,
        ) is None
    ]
    kept.sort(key=rank_key)
    return kept[: max(0, limit)]
