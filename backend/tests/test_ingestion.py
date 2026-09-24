"""Comprehensive ingestion tests.

Covers:
  - RSS parsing (feedparser) into DiscoveredEntry objects
  - discover_articles inserts new rows + is idempotent (URL dedup)
  - extract_articles advances state discovered → extracted
  - retry rule: 3 failures → failed_extract, attempt_count increments,
    successful attempt after failures resets attempt_count to 0
  - HashEmbedder produces 384-dim normalized vectors, similar texts get
    similar vectors
  - embed_articles advances state extracted → embedded
  - cluster_articles: article with no neighbors creates new story;
    subsequent similar article attaches to it
  - stories.article_count and last_seen_at update correctly
  - orchestrator writes a valid ingestion_runs row with status='success'
  - INGESTION_ENABLED=false short-circuits with status='skipped'
  - HashEmbedder → identical text pairs yield cosine 1.0
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import func, select, text

from src.db.models import Article, IngestionRun, Outlet, Story
from src.ingestion.cluster import cluster_articles
from src.ingestion.embed import EMBED_DIM, HashEmbedder, embed_articles
from src.ingestion.fetch import (
    MAX_ATTEMPTS,
    discover_articles,
    extract_articles,
    parse_feed,
)
from src.ingestion.outlets import load_outlets
from src.ingestion.run import run_once

from .conftest import FakeFetcher, FakeResponse, make_article_html, make_rss

_ = timedelta  # keep import in case tests reference it directly


# ---------------------------------------------------------------------------
# Pure unit tests — no DB
# ---------------------------------------------------------------------------
def test_parse_feed_extracts_expected_fields():
    xml = make_rss([
        {"title": "Budget lauded", "link": "https://x.example/a1",
         "pubDate": "Mon, 15 Sep 2026 08:30:00 +0000", "author": "R. Kumar"},
        {"title": "Budget tepid",  "link": "https://x.example/a2",
         "pubDate": "Mon, 15 Sep 2026 09:00:00 +0000"},
    ])
    entries = parse_feed(xml)
    assert len(entries) == 2
    e = entries[0]
    assert e.url == "https://x.example/a1"
    assert e.headline == "Budget lauded"
    assert e.author == "R. Kumar"
    assert e.published_at.tzinfo is not None


def test_parse_feed_skips_missing_url_or_date():
    xml = make_rss([{"title": "no link", "link": ""}])
    # no pubDate is deliberately missing → skipped
    xml = xml.replace("<pubDate", "<x-nope").replace("</pubDate>", "</x-nope>")
    assert parse_feed(xml) == []


def test_hash_embedder_shape_and_normalization():
    emb = HashEmbedder()
    assert emb.dim == EMBED_DIM
    vecs = emb.encode(["budget economy tax", "cricket sports match"])
    assert vecs.shape == (2, EMBED_DIM)
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_hash_embedder_similarity_for_overlap():
    emb = HashEmbedder()
    v = emb.encode([
        "budget 2026 tax reform",
        "budget 2026 tax reform announcement",   # near-duplicate
        "cricket world cup semifinal preview",   # unrelated
    ])
    sim_dup = float(v[0] @ v[1])
    sim_unrelated = float(v[0] @ v[2])
    assert sim_dup > 0.6
    assert sim_unrelated < 0.3


# ---------------------------------------------------------------------------
# Outlet registry
# ---------------------------------------------------------------------------
def test_outlets_yaml_has_five_phase1_outlets_with_slugs():
    specs = load_outlets(["phase_1"])
    assert len(specs) == 5
    assert {s.slug for s in specs} == {
        "the-hindu", "times-of-india", "indian-express", "ndtv", "hindustan-times"
    }
    for s in specs:
        assert s.rss_url.startswith("https://"), s
        assert s.website.startswith("https://"), s
        assert s.name


# ---------------------------------------------------------------------------
# DB-touching tests
# ---------------------------------------------------------------------------
def _make_outlet(db_session, slug="_test_hindu", name="_test hindu",
                 rss="https://x.example/rss") -> Outlet:
    o = Outlet(name=name, slug=slug, rss_url=rss, website="https://x.example", active=True)
    db_session.add(o)
    db_session.commit()
    return o


def test_discover_inserts_new_articles(db_session):
    outlet = _make_outlet(db_session)
    xml = make_rss([
        {"title": "_test A", "link": "_test_url_a",
         "pubDate": "Mon, 15 Sep 2026 08:30:00 +0000"},
        {"title": "_test B", "link": "_test_url_b",
         "pubDate": "Mon, 15 Sep 2026 09:00:00 +0000"},
    ])
    fetcher = FakeFetcher({outlet.rss_url: FakeResponse(200, xml)})

    n = discover_articles(db_session, outlet, fetcher=fetcher)
    assert n == 2

    rows = db_session.scalars(
        select(Article).where(Article.outlet_id == outlet.id).order_by(Article.id)
    ).all()
    assert len(rows) == 2
    assert all(r.processing_state == "discovered" for r in rows)
    assert rows[0].headline == "_test A"
    assert rows[0].url == "_test_url_a"


def test_discover_is_idempotent_no_duplicates(db_session):
    outlet = _make_outlet(db_session, slug="_test_ndtv")
    xml = make_rss([
        {"title": "_test C", "link": "_test_url_c",
         "pubDate": "Mon, 15 Sep 2026 08:30:00 +0000"},
    ])
    fetcher = FakeFetcher({outlet.rss_url: FakeResponse(200, xml)})

    n1 = discover_articles(db_session, outlet, fetcher=fetcher)
    n2 = discover_articles(db_session, outlet, fetcher=fetcher)  # second run
    n3 = discover_articles(db_session, outlet, fetcher=fetcher)  # third run

    assert n1 == 1
    assert n2 == 0
    assert n3 == 0

    count = db_session.scalar(
        select(func.count()).select_from(Article).where(Article.outlet_id == outlet.id)
    )
    assert count == 1


def test_extract_advances_state_and_stores_body(db_session):
    outlet = _make_outlet(db_session, slug="_test_ie")
    url = "_test_url_extract_ok"
    xml = make_rss([{"title": "_test D", "link": url,
                     "pubDate": "Mon, 15 Sep 2026 08:30:00 +0000"}])
    html = make_article_html("_test D", "This is the body of the article. " * 20)
    fetcher = FakeFetcher({
        outlet.rss_url: FakeResponse(200, xml),
        url:            FakeResponse(200, html),
    })
    discover_articles(db_session, outlet, fetcher=fetcher)

    extracted, failed = extract_articles(db_session, fetcher=fetcher,
                                         outlet_id=outlet.id)
    assert extracted == 1
    assert failed == 0

    a = db_session.scalar(select(Article).where(Article.url == url))
    assert a.processing_state == "extracted"
    assert a.full_text and "body of the article" in a.full_text
    assert a.attempt_count == 0
    assert a.state_error is None


def test_extract_retries_then_gives_up_after_max_attempts(db_session):
    outlet = _make_outlet(db_session, slug="_test_theprint")
    url = "_test_url_hard_fail"
    xml = make_rss([{"title": "_test E", "link": url,
                     "pubDate": "Mon, 15 Sep 2026 08:30:00 +0000"}])
    fetcher = FakeFetcher({
        outlet.rss_url: FakeResponse(200, xml),
        url:            FakeResponse(500, b""),   # always 500
    })
    discover_articles(db_session, outlet, fetcher=fetcher)

    # Attempts 1..MAX_ATTEMPTS
    for i in range(1, MAX_ATTEMPTS + 1):
        extract_articles(db_session, fetcher=fetcher, outlet_id=outlet.id)
        db_session.expire_all()
        a = db_session.scalar(select(Article).where(Article.url == url))
        if i < MAX_ATTEMPTS:
            assert a.processing_state == "discovered", f"iter {i}"
            assert a.attempt_count == i
            assert a.state_error and "500" in a.state_error
        else:
            assert a.processing_state == "failed_extract", f"iter {i}"
            assert a.attempt_count == MAX_ATTEMPTS
            assert a.state_error and "500" in a.state_error

    # A subsequent extract call should NOT touch the failed article.
    extracted_after, _ = extract_articles(db_session, fetcher=fetcher,
                                          outlet_id=outlet.id)
    assert extracted_after == 0


def test_extract_success_after_transient_failures_resets_attempt_count(db_session):
    outlet = _make_outlet(db_session, slug="_test_toi")
    url = "_test_url_transient"
    xml = make_rss([{"title": "_test F", "link": url,
                     "pubDate": "Mon, 15 Sep 2026 08:30:00 +0000"}])
    good_html = make_article_html("_test F", "Recoverable extraction body. " * 20)

    # First attempt returns 503, second returns 200
    class ToggleFetcher(FakeFetcher):
        def __init__(self, rss_url, article_url):
            super().__init__()
            self._rss_url = rss_url
            self._article_url = article_url
            self._calls_to_article = 0

        def get(self, url, *, timeout=None):
            self.calls.append(url)
            if url == self._rss_url:
                return FakeResponse(200, xml, url)
            if url == self._article_url:
                self._calls_to_article += 1
                if self._calls_to_article == 1:
                    return FakeResponse(503, b"", url)
                return FakeResponse(200, good_html, url)
            return FakeResponse(404, b"", url)

    fetcher = ToggleFetcher(outlet.rss_url, url)
    discover_articles(db_session, outlet, fetcher=fetcher)

    # Attempt 1 → 503 → attempt_count=1, still discovered
    extract_articles(db_session, fetcher=fetcher, outlet_id=outlet.id)
    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.url == url))
    assert a.processing_state == "discovered"
    assert a.attempt_count == 1

    # Attempt 2 → 200 → extracted, attempt_count reset to 0
    extract_articles(db_session, fetcher=fetcher, outlet_id=outlet.id)
    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.url == url))
    assert a.processing_state == "extracted"
    assert a.attempt_count == 0
    assert a.state_error is None


def test_embed_advances_state_and_writes_vector(db_session):
    outlet = _make_outlet(db_session, slug="_test_embed")
    url = "_test_url_embed"
    xml = make_rss([{"title": "_test G", "link": url,
                     "pubDate": "Mon, 15 Sep 2026 08:30:00 +0000"}])
    html = make_article_html("_test G", "Some body text about the budget. " * 20)
    fetcher = FakeFetcher({outlet.rss_url: FakeResponse(200, xml),
                           url: FakeResponse(200, html)})
    discover_articles(db_session, outlet, fetcher=fetcher)
    extract_articles(db_session, fetcher=fetcher, outlet_id=outlet.id)

    n = embed_articles(db_session, embedder=HashEmbedder())
    assert n == 1

    a = db_session.scalar(select(Article).where(Article.url == url))
    assert a.processing_state == "embedded"
    assert a.embedding is not None
    # pgvector round-trips as a list/np-like; length must be 384
    assert len(list(a.embedding)) == EMBED_DIM


def test_cluster_creates_new_story_and_attaches_similar_article(db_session):
    outlet = _make_outlet(db_session, slug="_test_cluster")
    urls = ["_test_url_c1", "_test_url_c2", "_test_url_unrelated"]
    # Use recent dates — the cluster lookback is only 3 days.
    now = datetime.now(tz=timezone.utc)
    fmt = "%a, %d %b %Y %H:%M:%S +0000"
    xml = make_rss([
        {"title": "_test Budget 2026 tax reforms hailed", "link": urls[0],
         "pubDate": (now - timedelta(hours=6)).strftime(fmt)},
        {"title": "_test Budget 2026 tax reform announcement details", "link": urls[1],
         "pubDate": (now - timedelta(hours=5)).strftime(fmt)},
        {"title": "_test Cricket world cup semifinal upset", "link": urls[2],
         "pubDate": (now - timedelta(hours=4)).strftime(fmt)},
    ])
    body_budget = "The union budget 2026 introduced sweeping tax reforms. " * 20
    body_cricket = "In an unexpected upset, the underdog side clinched the semifinal. " * 20

    fetcher = FakeFetcher({
        outlet.rss_url: FakeResponse(200, xml),
        urls[0]: FakeResponse(200, make_article_html("_test budget A",
                                                     body_budget)),
        urls[1]: FakeResponse(200, make_article_html("_test budget B",
                                                     body_budget + " related coverage.")),
        urls[2]: FakeResponse(200, make_article_html("_test cricket", body_cricket)),
    })
    discover_articles(db_session, outlet, fetcher=fetcher)
    extract_articles(db_session, fetcher=fetcher, outlet_id=outlet.id)
    embed_articles(db_session, embedder=HashEmbedder())

    result = cluster_articles(db_session, threshold=0.5)  # relaxed for HashEmbedder
    assert result.articles_clustered == 3
    # 2 stories: one for budget (the two similar articles), one for cricket.
    assert result.new_stories == 2
    assert result.attached_to_existing == 1

    rows = db_session.scalars(
        select(Article).where(Article.url.in_(urls)).order_by(Article.id)
    ).all()
    story_ids = {r.story_id for r in rows}
    assert len(story_ids) == 2
    assert all(r.processing_state == "clustered" for r in rows)

    # article_count on stories
    counts = {
        s.id: s.article_count
        for s in db_session.scalars(
            select(Story).where(Story.id.in_(story_ids))
        ).all()
    }
    # one story has 2 articles, the other has 1
    assert sorted(counts.values()) == [1, 2]


def test_orchestrator_records_ingestion_run_success(db_session, monkeypatch):
    outlet = _make_outlet(db_session, slug="the-hindu",
                          rss="_test_rss_the_hindu")

    xml = make_rss([{"title": "_test orch A", "link": "_test_url_orch_a",
                     "pubDate": "Mon, 15 Sep 2026 08:30:00 +0000"}])
    html = make_article_html("_test orch A", "Orchestrator smoke body. " * 20)

    class Factory(FakeFetcher):
        def __init__(self):
            super().__init__({
                "_test_rss_the_hindu": FakeResponse(200, xml),
                "_test_url_orch_a":    FakeResponse(200, html),
            })

    # Give run_once a real DATABASE_URL — same as our fixture's DB.
    # align_run_db_to_test_db forces DATABASE_URL := DATABASE_URL_TEST
    # (when set) and clears the settings cache so run_once() reads the
    # dev-test DB, not whatever DATABASE_URL in .env points at.
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL",  "test")
    from .conftest import align_run_db_to_test_db
    align_run_db_to_test_db(monkeypatch)

    started = datetime.now(tz=timezone.utc)
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=Factory,
    )
    assert rc == 0

    # The most-recent 'manual' ingestion_runs row started >= our reference
    # time should be this test's run.
    run = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc())
        .limit(1)
    )
    assert run is not None
    assert run.status == "success"
    assert run.articles_discovered >= 1
    assert run.articles_inserted >= 1
    assert run.completed_at is not None


def test_orchestrator_records_skipped_when_disabled(db_session, monkeypatch):
    monkeypatch.setenv("INGESTION_ENABLED", "false")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL",  "test")
    from .conftest import align_run_db_to_test_db
    align_run_db_to_test_db(monkeypatch)

    started = datetime.now(tz=timezone.utc)
    rc = run_once(phases=["phase_1"], embedder=HashEmbedder(),
                  triggered_by="manual")
    assert rc == 0

    run = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc())
        .limit(1)
    )
    assert run is not None
    assert run.status == "skipped"


# ---------------------------------------------------------------------------
# Batch-drain tests
# ---------------------------------------------------------------------------
def test_extract_drains_with_small_batch_limit(db_session):
    """extract_articles with batch_limit=5 needs multiple calls to drain 12 articles."""
    outlet = _make_outlet(db_session, slug="_test_drain_ext")
    n = 12
    now = datetime.now(tz=timezone.utc)
    fmt = "%a, %d %b %Y %H:%M:%S +0000"

    items = []
    responses: dict[str, FakeResponse] = {}
    for i in range(n):
        url = f"_test_drain_ext_{i:03d}"
        pub = (now - timedelta(hours=n - i)).strftime(fmt)
        items.append({"title": f"_test drain ext {i}", "link": url, "pubDate": pub})
        body = f"Body for drain extraction test article number {i}. " * 20
        responses[url] = FakeResponse(200, make_article_html(f"_test drain ext {i}", body))

    xml = make_rss(items)
    responses[outlet.rss_url] = FakeResponse(200, xml)
    fetcher = FakeFetcher(responses)

    discover_articles(db_session, outlet, fetcher=fetcher)

    # Drain with batch_limit=5 — should take 3 productive + 1 empty call
    total_extracted = 0
    calls = 0
    while True:
        extracted, failed = extract_articles(db_session, fetcher=fetcher,
                                               batch_limit=5, outlet_id=outlet.id)
        total_extracted += extracted
        calls += 1
        if extracted == 0 and failed == 0:
            break

    assert total_extracted == n
    assert calls == 4  # 5 + 5 + 2 + 0(break)

    # All articles should now be in 'extracted' state
    rows = db_session.scalars(
        select(Article).where(Article.url.like("_test_drain_ext_%"))
    ).all()
    assert all(r.processing_state == "extracted" for r in rows)


def test_orchestrator_drains_all_articles_beyond_batch_limit(db_session, monkeypatch):
    """run_once processes >100 articles through the full pipeline in one call."""
    outlet = _make_outlet(db_session, slug="the-hindu", rss="_test_rss_drain")

    n_articles = 120  # > default batch_limit of 100
    now = datetime.now(tz=timezone.utc)
    fmt = "%a, %d %b %Y %H:%M:%S +0000"

    items = []
    responses: dict[str, FakeResponse] = {}
    for i in range(n_articles):
        url = f"_test_drain_{i:04d}"
        pub = (now - timedelta(hours=n_articles - i)).strftime(fmt)
        items.append({"title": f"_test drain article {i}", "link": url, "pubDate": pub})
        body = f"Unique body text for drain test article number {i} topic_{i % 7}. " * 20
        responses[url] = FakeResponse(200, make_article_html(f"_test drain {i}", body))

    xml = make_rss(items)
    responses["_test_rss_drain"] = FakeResponse(200, xml)

    class DrainFactory(FakeFetcher):
        def __init__(self):
            super().__init__(responses)

    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL", "test")
    from .conftest import align_run_db_to_test_db
    align_run_db_to_test_db(monkeypatch)

    started = datetime.now(tz=timezone.utc)
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=DrainFactory,
    )
    assert rc == 0

    # Every article should have reached 'clustered' state
    state_counts = dict(
        db_session.execute(
            select(Article.processing_state, func.count())
            .where(Article.url.like("_test_drain_%"))
            .group_by(Article.processing_state)
        ).all()
    )
    assert state_counts.get("clustered", 0) == n_articles, (
        f"Expected all {n_articles} in 'clustered', got: {state_counts}"
    )
    assert "discovered" not in state_counts
    assert "extracted" not in state_counts
    assert "embedded" not in state_counts

    # Ingestion run row should reflect the full count
    run_row = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc())
        .limit(1)
    )
    assert run_row is not None
    assert run_row.status == "success"
    assert run_row.articles_discovered == n_articles
    assert run_row.articles_inserted == n_articles
