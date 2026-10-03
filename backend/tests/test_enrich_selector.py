"""Focused tests for the Home-priority enrichment selector.

Exercises ``src.ingestion.enrich._select_clustered_prioritized`` — the
query that decides which clustered articles the next LLM call will
enrich. The old flat ORDER BY let a single large story (observed on
dev: story 1805 — 9 outlets, 118 articles) take all 20 slots per
cycle, leaving every other Home-visible story with no framing data.
The rewrite enforces three invariants, each covered below:

  1. **Per-story cap.** No single story contributes more than
     ``llm_enrich_per_story_cap`` articles to one call.
  2. **Home-priority tier.** The top-N Home stories (by the same
     ordering the frontend's Hot Now uses) outrank every non-Home
     story, including non-Home stories with more outlets.
  3. **Outlet-diversity within a story.** The first ``cap`` articles
     taken from a story are from different outlets whenever at least
     ``cap`` outlets have clustered articles there.
  4. **Non-Home still competes.** After Home-top is served, leftover
     slots flow to the P1 then P2 non-Home tiers unchanged.
  5. **attempt_count + min-outlets filters.** Articles with
     ``attempt_count >= MAX_ATTEMPTS`` and articles in single-outlet
     stories are excluded, as before.

Every test uses ``_test_sel_%``-prefixed outlet slugs and
``_dbg_%``-titled stories so the ``db_session`` cleanup pattern wipes
them cleanly. Tests pass ``story_ids=`` to ``_select_clustered_prioritized``
so the production ordering runs only against the test fixtures — no
risk of picking up unrelated real coverage from the shared dev-test DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.db.models import (
    Article,
    ArticleAnalysis,
    AnalysisRun,
    Outlet,
    Story,
    StoryComparison,
)
from src.ingestion.enrich import (
    COVERAGE_PRIORITY_MIN_OUTLETS,
    HOME_PRIORITY_TOP_N,
    MAX_ATTEMPTS,
    _select_clustered_prioritized,
)


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------
def _make_outlet(db_session, slug: str) -> Outlet:
    o = Outlet(
        name=f"_test outlet {slug}",
        slug=slug,
        rss_url=f"https://x.example/{slug}",
        website="https://x.example",
        active=True,
    )
    db_session.add(o)
    db_session.flush()
    return o


def _make_story(
    db_session, *, title: str, last_seen_offset_hours: float = 1.0,
    first_seen_offset_hours: float = 24.0,
) -> Story:
    """Create a story with a configurable ``last_seen_at`` relative to NOW.

    Default last_seen_offset=1h → the story is INSIDE the Home 72h
    freshness window. Pass a larger offset (e.g. 96) to make the story
    stale (outside Home-top eligibility).
    """
    now = datetime.now(tz=timezone.utc)
    s = Story(
        title=title,
        first_seen_at=now - timedelta(hours=first_seen_offset_hours),
        last_seen_at=now - timedelta(hours=last_seen_offset_hours),
        article_count=0,
    )
    db_session.add(s)
    db_session.flush()
    return s


def _make_article(
    db_session, *, outlet: Outlet, story: Story, url_tag: str,
    processing_state: str = "clustered",
    attempt_count: int = 0,
    published_hours_ago: float = 1.0,
) -> Article:
    now = datetime.now(tz=timezone.utc)
    a = Article(
        outlet_id=outlet.id,
        url=f"_test_url_sel_{url_tag}",
        headline=f"_dbg_ article {url_tag}",
        published_at=now - timedelta(hours=published_hours_ago),
        full_text=f"body {url_tag}",
        story_id=story.id,
        processing_state=processing_state,
        attempt_count=attempt_count,
    )
    db_session.add(a)
    db_session.flush()
    return a


def _bump_story_counters(db_session, story: Story) -> None:
    """Recompute article_count from the inserted articles so it
    matches reality (the selector reads n_articles via the CTE from
    the ``articles`` table itself, so this is only cosmetic — but
    keeps the fixture honest with the schema)."""
    n = db_session.scalar(
        select(Article).where(Article.story_id == story.id)
                       .where(Article.processing_state.in_(
                            ("clustered", "analyzed", "complete")))
                       .with_only_columns(Article.id)
                       .limit(1)
    )
    if n is None:
        story.article_count = 0
    else:
        story.article_count = db_session.query(Article)\
            .filter(Article.story_id == story.id)\
            .count()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test 1 — per-story cap
# ---------------------------------------------------------------------------
def test_single_story_cannot_exceed_per_story_cap(db_session):
    """A story with far more than ``cap`` clustered articles must
    contribute at most ``cap`` rows to one selector call. Regression
    guard against the 1805-monopoly bug."""
    outlet_a = _make_outlet(db_session, "_test_sel_cap_a")
    outlet_b = _make_outlet(db_session, "_test_sel_cap_b")
    big = _make_story(db_session, title="_dbg_ cap-big-story")
    # 10 clustered articles across 2 outlets. With cap=4 the selector
    # must take exactly 4.
    for i in range(10):
        _make_article(
            db_session,
            outlet=(outlet_a if i % 2 == 0 else outlet_b),
            story=big,
            url_tag=f"cap_{i:02d}",
            published_hours_ago=1.0 + i * 0.1,
        )
    db_session.commit()

    picked = _select_clustered_prioritized(
        db_session, batch_limit=20, story_ids=[big.id],
    )
    assert len(picked) == 4, (
        f"expected cap=4 articles, got {len(picked)}: {picked}"
    )
    # All picks must belong to this story — no cross-contamination.
    for aid, _slug in picked:
        a = db_session.get(Article, aid)
        assert a is not None and a.story_id == big.id


# ---------------------------------------------------------------------------
# Test 2 — Home-top beats higher-outlet non-Home
# ---------------------------------------------------------------------------
def test_home_top_outranks_non_home_with_more_outlets(db_session):
    """A Home-top story with FEWER outlets must come before a non-Home
    story with MORE outlets. This is the whole point of the Home-tier
    rewrite — the frontend's visible top must be analyzed first."""
    # Home-top story: 3 outlets, fresh (last_seen = 1h ago).
    out_h1 = _make_outlet(db_session, "_test_sel_h1")
    out_h2 = _make_outlet(db_session, "_test_sel_h2")
    out_h3 = _make_outlet(db_session, "_test_sel_h3")
    home_story = _make_story(
        db_session, title="_dbg_ home-top-3-outlets",
        last_seen_offset_hours=1.0,
    )
    for i, o in enumerate((out_h1, out_h2, out_h3)):
        _make_article(
            db_session, outlet=o, story=home_story,
            url_tag=f"home_{i}", published_hours_ago=1.0 + i * 0.1,
        )

    # Non-Home story: 5 outlets, STALE (last_seen 200h ago → outside
    # the 72h Home freshness window → cannot be Home-top).
    stale_outlets = [
        _make_outlet(db_session, f"_test_sel_stale_{i}") for i in range(5)
    ]
    stale_story = _make_story(
        db_session, title="_dbg_ stale-5-outlets",
        last_seen_offset_hours=200.0,
        first_seen_offset_hours=300.0,
    )
    for i, o in enumerate(stale_outlets):
        _make_article(
            db_session, outlet=o, story=stale_story,
            url_tag=f"stale_{i}", published_hours_ago=200.0 + i * 0.1,
        )
    db_session.commit()

    picked = _select_clustered_prioritized(
        db_session, batch_limit=20,
        story_ids=[home_story.id, stale_story.id],
    )
    # Home-top's 3 articles must appear BEFORE any stale-story article.
    # Build the position of each story's first row.
    first_pos_home = next(
        (i for i, (aid, _) in enumerate(picked)
         if db_session.get(Article, aid).story_id == home_story.id),
        None,
    )
    first_pos_stale = next(
        (i for i, (aid, _) in enumerate(picked)
         if db_session.get(Article, aid).story_id == stale_story.id),
        None,
    )
    assert first_pos_home is not None, "Home-top story not in results"
    assert first_pos_stale is not None, "Non-Home story not in results"
    assert first_pos_home < first_pos_stale, (
        f"Home-top story (pos={first_pos_home}) must outrank non-Home "
        f"story with more outlets (pos={first_pos_stale})"
    )


# ---------------------------------------------------------------------------
# Test 3 — outlet diversity within a story
# ---------------------------------------------------------------------------
def test_within_story_slots_prefer_different_outlets(db_session):
    """When a story has >= ``cap`` outlets each contributing a
    clustered article, the first ``cap`` picks must be from ``cap``
    DISTINCT outlets. Guards the ``rank_in_outlet`` ordering."""
    # 5 outlets, each with 2 clustered articles in the SAME story.
    # With cap=4 the picks should be 4 different outlets (1 article
    # per outlet — rank_in_outlet=1 for each).
    outlets = [
        _make_outlet(db_session, f"_test_sel_div_{i}") for i in range(5)
    ]
    s = _make_story(db_session, title="_dbg_ div-5-outlets")
    for i, o in enumerate(outlets):
        for j in range(2):
            _make_article(
                db_session, outlet=o, story=s,
                url_tag=f"div_{i}_{j}",
                published_hours_ago=1.0 + i * 0.1 + j * 0.01,
            )
    db_session.commit()

    picked = _select_clustered_prioritized(
        db_session, batch_limit=20, story_ids=[s.id],
    )
    assert len(picked) == 4
    picked_outlet_slugs = {slug for _aid, slug in picked}
    assert len(picked_outlet_slugs) == 4, (
        f"expected 4 distinct outlets in the cap=4 picks, "
        f"got {len(picked_outlet_slugs)}: {picked_outlet_slugs}"
    )


# ---------------------------------------------------------------------------
# Test 4 — non-Home stories still receive leftover slots
# ---------------------------------------------------------------------------
def test_non_home_multi_outlet_stories_get_leftover_slots(db_session):
    """When Home-top doesn't fill the full batch_limit, remaining
    slots must flow to multi-outlet non-Home stories (P1 then P2)."""
    # Home-top story: 2 outlets, 2 articles total. Takes 2 of a
    # batch_limit=10, leaving 8 slots.
    out_h1 = _make_outlet(db_session, "_test_sel_leftover_h1")
    out_h2 = _make_outlet(db_session, "_test_sel_leftover_h2")
    home_story = _make_story(
        db_session, title="_dbg_ leftover-home",
        last_seen_offset_hours=1.0,
    )
    _make_article(db_session, outlet=out_h1, story=home_story,
                  url_tag="leftover_h1", published_hours_ago=1.0)
    _make_article(db_session, outlet=out_h2, story=home_story,
                  url_tag="leftover_h2", published_hours_ago=1.5)

    # Non-Home multi-outlet story (stale), 4 articles across 2
    # outlets. Must receive the leftover slots.
    out_n1 = _make_outlet(db_session, "_test_sel_leftover_n1")
    out_n2 = _make_outlet(db_session, "_test_sel_leftover_n2")
    nonhome_story = _make_story(
        db_session, title="_dbg_ leftover-nonhome",
        last_seen_offset_hours=200.0,
        first_seen_offset_hours=300.0,
    )
    for i, o in enumerate((out_n1, out_n2, out_n1, out_n2)):
        _make_article(
            db_session, outlet=o, story=nonhome_story,
            url_tag=f"leftover_n_{i}",
            published_hours_ago=200.0 + i * 0.1,
        )
    db_session.commit()

    picked = _select_clustered_prioritized(
        db_session, batch_limit=10,
        story_ids=[home_story.id, nonhome_story.id],
    )
    home_count = sum(
        1 for aid, _ in picked
        if db_session.get(Article, aid).story_id == home_story.id
    )
    nonhome_count = sum(
        1 for aid, _ in picked
        if db_session.get(Article, aid).story_id == nonhome_story.id
    )
    assert home_count == 2
    # Non-Home receives the leftover; capped at 4 so all 4 of its
    # clustered articles make it in.
    assert nonhome_count == 4, (
        f"non-Home story expected to receive 4 leftover slots, "
        f"got {nonhome_count}"
    )
    # Total picks = 6 (2 home + 4 non-home). batch_limit=10 allows
    # more but no further eligible articles exist.
    assert len(picked) == 6


# ---------------------------------------------------------------------------
# Test 5 — eligibility filters: attempt_count + n_outlets
# ---------------------------------------------------------------------------
def test_attempt_cap_and_single_outlet_filters_still_enforced(db_session):
    """The two existing eligibility filters must survive the rewrite:
      * articles with ``attempt_count >= MAX_ATTEMPTS`` are excluded;
      * stories with only one distinct outlet are excluded entirely.
    """
    # Single-outlet story — must be excluded even though it has
    # clustered articles and sits inside the Home freshness window.
    out_s = _make_outlet(db_session, "_test_sel_single_o")
    single_story = _make_story(
        db_session, title="_dbg_ single-outlet",
        last_seen_offset_hours=1.0,
    )
    _make_article(
        db_session, outlet=out_s, story=single_story,
        url_tag="single_1", published_hours_ago=1.0,
    )
    _make_article(
        db_session, outlet=out_s, story=single_story,
        url_tag="single_2", published_hours_ago=2.0,
    )

    # Multi-outlet story with 3 clustered articles, one of which has
    # attempt_count = MAX_ATTEMPTS (= 3) — that article must be
    # excluded; the other two must appear.
    out_m1 = _make_outlet(db_session, "_test_sel_multi_1")
    out_m2 = _make_outlet(db_session, "_test_sel_multi_2")
    multi_story = _make_story(
        db_session, title="_dbg_ multi-attempt",
        last_seen_offset_hours=1.0,
    )
    good_a = _make_article(
        db_session, outlet=out_m1, story=multi_story,
        url_tag="multi_ok_1", published_hours_ago=1.0,
    )
    good_b = _make_article(
        db_session, outlet=out_m2, story=multi_story,
        url_tag="multi_ok_2", published_hours_ago=1.5,
    )
    _make_article(
        db_session, outlet=out_m1, story=multi_story,
        url_tag="multi_capped",
        attempt_count=MAX_ATTEMPTS,  # exactly at the cap → excluded
        published_hours_ago=2.0,
    )
    db_session.commit()

    picked = _select_clustered_prioritized(
        db_session, batch_limit=20,
        story_ids=[single_story.id, multi_story.id],
    )
    picked_ids = {aid for aid, _ in picked}

    # Single-outlet story: zero picks.
    for aid, _slug in picked:
        a = db_session.get(Article, aid)
        assert a.story_id != single_story.id, (
            "single-outlet story leaked into the selector result"
        )

    # Multi-outlet: the two attempt_count=0 articles are present;
    # the attempt_count=MAX_ATTEMPTS one is NOT.
    assert good_a.id in picked_ids
    assert good_b.id in picked_ids
    capped_ids = {
        a.id for a in db_session.query(Article)
        .filter(Article.story_id == multi_story.id)
        .filter(Article.attempt_count >= MAX_ATTEMPTS)
        .all()
    }
    assert not (capped_ids & picked_ids), (
        f"article(s) at or over attempt-cap leaked in: "
        f"{capped_ids & picked_ids}"
    )


# ---------------------------------------------------------------------------
# Bonus smoke — the HOME_PRIORITY_TOP_N constant is a sensible value
# ---------------------------------------------------------------------------
def test_home_priority_top_n_matches_frontend_hot_now_count():
    """``HOME_PRIORITY_TOP_N`` must stay in sync with the frontend's
    ``HOT_NOW_COUNT`` (8) so the stories the user sees at the top of
    Home are the stories the selector prioritizes. If the frontend
    changes the number of Hot-Now items this test fails and forces a
    deliberate review."""
    assert HOME_PRIORITY_TOP_N == 8


def test_coverage_priority_min_outlets_is_two():
    """The documented minimum outlet count for enrichment eligibility
    is 2 (compare's MIN_OUTLETS). Guards against an accidental drift."""
    assert COVERAGE_PRIORITY_MIN_OUTLETS == 2
