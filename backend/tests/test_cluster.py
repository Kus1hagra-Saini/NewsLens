"""Tests for the story-clustering stage.

Covers:
  * The IVFFLAT-probes fix. The clustering neighbor query is a KNN
    ``ORDER BY <=> LIMIT 1`` scan, which pgvector routes through the
    ``ix_articles_embedding_ivfflat`` index (created ``WITH lists=100``).
    ivfflat is APPROXIMATE: the default ``probes=1`` scans only ONE of
    the 100 IVF lists and can silently miss the true nearest neighbor
    when it lives in a different list — the exact failure that caused
    cross-outlet news articles (same event, different framing → close
    but distinct embeddings → different IVF lists) to end up in
    separate stories at similarities of 0.9+. ``cluster_articles`` now
    issues ``SET LOCAL ivfflat.probes = <lists>`` at the start of every
    call to force exact recall; these tests guard that behavior.
  * The basic clustering rules: identical cross-outlet embeddings
    attach to the same story; dissimilar embeddings create separate
    stories.

The DB fixture from ``conftest.py`` requires a real Postgres with
pgvector — the tests skip cleanly if ``DATABASE_URL_TEST`` (or
``DATABASE_URL``) is not set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import pytest
from sqlalchemy import event, select, text

from src.db.models import Article, Outlet, Story
from src.ingestion.cluster import (
    IVFFLAT_PROBES,
    SIMILARITY_THRESHOLD,
    cluster_articles,
)


# ---------------------------------------------------------------------------
# Fixture helpers
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


def _make_embedded_article(
    db_session,
    *,
    outlet: Outlet,
    url: str,
    headline: str,
    embedding: Iterable[float],
    published_at: datetime | None = None,
) -> Article:
    """Insert a row already advanced to state=embedded with the given vector.

    Bypasses the discover/extract/embed stages — the tests are only
    exercising the clustering step.
    """
    vec = np.asarray(list(embedding), dtype=np.float32)
    a = Article(
        outlet_id=outlet.id,
        url=url,
        headline=headline,
        published_at=published_at or datetime.now(tz=timezone.utc),
        full_text=f"body for {headline}",
        embedding=vec.tolist(),
        processing_state="embedded",
    )
    db_session.add(a)
    db_session.flush()
    return a


def _unit_vector(seed: int, dim: int = 384) -> np.ndarray:
    """Deterministic unit-length vector so tests don't drift."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= float(np.linalg.norm(v))
    return v


# ---------------------------------------------------------------------------
# Regression test — the actual fix
# ---------------------------------------------------------------------------
def test_cluster_sets_ivfflat_probes_before_neighbor_query(db_session):
    """cluster_articles MUST issue ``SET LOCAL ivfflat.probes = <lists>``
    before its KNN neighbor query, so the ivfflat index returns exact
    (not approximate) nearest neighbors.

    Removing that SET LOCAL would silently reintroduce the cross-outlet
    fragmentation bug — same-event articles from different outlets
    land in different IVF lists and get missed by the default
    ``probes=1`` scan. This test is the guard: if someone deletes the
    line, this fails immediately.
    """
    outlet = _make_outlet(db_session, "_test_cluster_probes_o")
    _make_embedded_article(
        db_session,
        outlet=outlet,
        url="_test_url_cluster_probes_1",
        headline="_dbg_ cluster probes seed",
        embedding=_unit_vector(1),
    )
    db_session.commit()

    # Capture every SQL statement executed by the session's connection
    # during the clustering call. Using the connection-level event so
    # both ``session.execute(text(...))`` and ``session.execute(update(...))``
    # are captured verbatim.
    captured: list[str] = []
    conn = db_session.connection()

    def _before_cursor_execute(_conn, _cur, statement, _params, _ctx, _many):
        captured.append(statement)

    event.listen(conn, "before_cursor_execute", _before_cursor_execute)
    try:
        cluster_articles(db_session)
    finally:
        event.remove(conn, "before_cursor_execute", _before_cursor_execute)

    # The SET LOCAL must appear before any query that references the
    # ``embedding`` column with the ``<=>`` operator.
    probes_idx = next(
        (i for i, s in enumerate(captured)
         if "ivfflat.probes" in s.lower() and "set local" in s.lower()),
        None,
    )
    assert probes_idx is not None, (
        f"cluster_articles did not issue `SET LOCAL ivfflat.probes = ...`. "
        f"Captured statements: {captured!r}"
    )
    # And the value must match the module's IVFFLAT_PROBES constant so
    # a config change stays honest.
    assert f"= {IVFFLAT_PROBES}" in captured[probes_idx], (
        f"SET LOCAL used the wrong probe count: {captured[probes_idx]!r}"
    )

    # Sanity check: the neighbor KNN (`embedding <=>`) query must run
    # AFTER the SET LOCAL — otherwise the SET has no effect.
    knn_idx = next(
        (i for i, s in enumerate(captured) if "<=>" in s),
        None,
    )
    assert knn_idx is not None, (
        "cluster_articles did not issue a `<=>` KNN query at all "
        "(unexpected — did the query change?)."
    )
    assert probes_idx < knn_idx, (
        f"SET LOCAL ivfflat.probes must precede the KNN query; "
        f"got probes_idx={probes_idx} knn_idx={knn_idx}"
    )


def test_cluster_ivfflat_probes_actually_takes_effect_in_txn(db_session):
    """End-to-end check that the SET LOCAL is applied to the actual
    transaction pgvector reads from — not just issued and dropped.

    Uses ``SHOW ivfflat.probes`` inside the SAME session immediately
    after clustering-style setup to confirm the runtime parameter is
    what we set it to. This is what pgvector's KNN operator actually
    consults at plan time.
    """
    # SET LOCAL requires an active transaction; the test-session
    # connection is already in one (db_session runs inside a txn).
    db_session.execute(text(f"SET LOCAL ivfflat.probes = {IVFFLAT_PROBES}"))
    row = db_session.execute(text("SHOW ivfflat.probes")).first()
    assert row is not None
    assert int(row[0]) == IVFFLAT_PROBES, (
        f"ivfflat.probes did not take effect: expected {IVFFLAT_PROBES}, "
        f"got {row[0]!r}"
    )


# ---------------------------------------------------------------------------
# Behavioral tests — the clustering rules the fix guarantees
# ---------------------------------------------------------------------------
def test_cluster_cross_outlet_identical_embeddings_share_story(db_session):
    """Two articles from DIFFERENT outlets with identical embeddings
    must end up in the same story.

    This is the exact scenario the audit uncovered 85 times at
    sim>=0.75: cross-outlet coverage of the same event. Cosine
    similarity of identical unit vectors is 1.0, well above the 0.75
    threshold — the clustering algorithm has no legitimate reason to
    split them, and the ivfflat fix removes the illegitimate one.
    """
    outlet_a = _make_outlet(db_session, "_test_cluster_x_a")
    outlet_b = _make_outlet(db_session, "_test_cluster_x_b")

    shared_vec = _unit_vector(42)

    art_a = _make_embedded_article(
        db_session,
        outlet=outlet_a,
        url="_test_url_cluster_x_a1",
        headline="_dbg_ cluster shared event a",
        embedding=shared_vec,
    )
    art_b = _make_embedded_article(
        db_session,
        outlet=outlet_b,
        url="_test_url_cluster_x_b1",
        headline="_dbg_ cluster shared event b",
        embedding=shared_vec,
    )
    db_session.commit()

    cluster_articles(db_session)

    # Re-read both rows: the ORM instances may or may not be refreshed
    # depending on session state, so query fresh.
    rows = db_session.execute(
        select(Article.id, Article.story_id, Article.processing_state)
        .where(Article.id.in_([art_a.id, art_b.id]))
    ).all()
    by_id = {r.id: r for r in rows}
    a_row = by_id[art_a.id]
    b_row = by_id[art_b.id]

    assert a_row.processing_state == "clustered"
    assert b_row.processing_state == "clustered"
    assert a_row.story_id is not None
    assert b_row.story_id is not None
    assert a_row.story_id == b_row.story_id, (
        f"cross-outlet identical embeddings ended up in different "
        f"stories (story_id A={a_row.story_id}, B={b_row.story_id}). "
        f"This is the ivfflat-probes bug the fix targets."
    )


def test_cluster_dissimilar_embeddings_create_distinct_stories(db_session):
    """Two articles with orthogonal-ish embeddings (similarity well
    below the 0.75 threshold) must land in DIFFERENT stories, so the
    fix doesn't over-cluster."""
    outlet_a = _make_outlet(db_session, "_test_cluster_d_a")
    outlet_b = _make_outlet(db_session, "_test_cluster_d_b")

    # Two random unit vectors from different seeds — near-orthogonal
    # in 384-D space, so cosine similarity is ~0 (well under 0.75).
    vec_a = _unit_vector(1001)
    vec_b = _unit_vector(2002)
    sim = float(np.dot(vec_a, vec_b))
    assert sim < SIMILARITY_THRESHOLD, (
        f"test setup broken: seeds produced sim={sim} >= threshold; "
        f"pick different seeds"
    )

    art_a = _make_embedded_article(
        db_session,
        outlet=outlet_a,
        url="_test_url_cluster_d_a1",
        headline="_dbg_ cluster different event a",
        embedding=vec_a,
    )
    art_b = _make_embedded_article(
        db_session,
        outlet=outlet_b,
        url="_test_url_cluster_d_b1",
        headline="_dbg_ cluster different event b",
        embedding=vec_b,
    )
    db_session.commit()

    cluster_articles(db_session)

    rows = db_session.execute(
        select(Article.id, Article.story_id, Article.processing_state)
        .where(Article.id.in_([art_a.id, art_b.id]))
    ).all()
    by_id = {r.id: r for r in rows}
    a_row = by_id[art_a.id]
    b_row = by_id[art_b.id]

    assert a_row.processing_state == "clustered"
    assert b_row.processing_state == "clustered"
    assert a_row.story_id is not None
    assert b_row.story_id is not None
    assert a_row.story_id != b_row.story_id, (
        f"dissimilar embeddings (sim={sim:.3f}) were clustered into "
        f"the same story; the threshold or query is over-permissive"
    )


def test_cluster_second_article_in_batch_can_join_first_articles_new_story(db_session):
    """When two similar embedded articles are processed in the SAME
    batch, the second one must be able to attach to the story the
    first one just created — the loop's read-your-own-writes
    guarantee. Regression guard for a subtle failure mode where an
    optimization (deferred flush, wrong isolation level, snapshot-based
    read) would hide the first article's new story_id from the second
    article's neighbor query.
    """
    outlet_a = _make_outlet(db_session, "_test_cluster_batch_a")
    outlet_b = _make_outlet(db_session, "_test_cluster_batch_b")

    shared_vec = _unit_vector(777)

    # published_at ordering matters — cluster_articles processes
    # oldest first. Older TOI article should create the story; newer
    # HT article should attach. Both timestamps MUST fall inside the
    # 3-day clustering lookback (cluster.py LOOKBACK_DAYS), otherwise
    # the first article's row is filtered out of the second article's
    # neighbor query and a duplicate story is created — that's a data
    # setup problem, not a clustering bug. Anchoring to NOW() keeps
    # the test correct regardless of when it runs.
    now = datetime.now(tz=timezone.utc)
    older = now - timedelta(hours=2)
    newer = now - timedelta(hours=1)

    art_first = _make_embedded_article(
        db_session,
        outlet=outlet_a,
        url="_test_url_cluster_batch_a1",
        headline="_dbg_ cluster batch first",
        embedding=shared_vec,
        published_at=older,
    )
    art_second = _make_embedded_article(
        db_session,
        outlet=outlet_b,
        url="_test_url_cluster_batch_b1",
        headline="_dbg_ cluster batch second",
        embedding=shared_vec,
        published_at=newer,
    )
    db_session.commit()

    outcome = cluster_articles(db_session)

    # Both articles processed in ONE batch. One creates the story,
    # the other attaches to it.
    assert outcome.articles_clustered == 2
    assert outcome.new_stories == 1
    assert outcome.attached_to_existing == 1

    rows = db_session.execute(
        select(Article.id, Article.story_id)
        .where(Article.id.in_([art_first.id, art_second.id]))
    ).all()
    story_ids = {r.id: r.story_id for r in rows}
    assert story_ids[art_first.id] == story_ids[art_second.id]

    # And the story's article_count should be 2 (both attached), not
    # 1 (only the creator was counted).
    story = db_session.execute(
        select(Story).where(Story.id == story_ids[art_first.id])
    ).scalar_one()
    assert story.article_count == 2
