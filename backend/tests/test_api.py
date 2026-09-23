"""FastAPI HTTP layer tests.

Uses the sync ``db_session`` fixture from conftest.py to insert a small
test dataset (outlet + story + articles + analysis + comparison) with
the ``_test_*`` slug/URL prefix so conftest teardown cleans everything.

The TestClient shares the same Neon database as the sync test session;
after ``db_session.commit()`` runs, HTTP responses see the rows.

No real Groq calls. No external HTTP.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.models import (
    AnalysisRun,
    Article,
    ArticleAnalysis,
    IngestionRun,
    Outlet,
    Story,
    StoryComparison,
)


# ---------------------------------------------------------------------------
# TestClient fixture — uses the real DATABASE_URL from the environment so
# the app's async engine can reach the same Neon DB the sync test session
# writes to.
# ---------------------------------------------------------------------------
@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    real_db = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_TEST")
    if not real_db:
        pytest.skip("DATABASE_URL not set — API tests need the real DB")

    monkeypatch.setenv("DATABASE_URL",  real_db)
    monkeypatch.setenv("GROQ_API_KEY",  "test-api-key-not-used")
    monkeypatch.setenv("LLM_MODEL",     "test-model")
    monkeypatch.setenv("CORS_ORIGINS",  "http://localhost:5173")

    # Reset every cache that might be holding an earlier fixture's fake
    # values so the app reads THIS test's env.
    from src.config import get_settings
    get_settings.cache_clear()
    from src.db import session as db_session_mod
    db_session_mod._engine.cache_clear()
    db_session_mod._sessionmaker.cache_clear()

    from src.main import create_app
    app = create_app()
    with TestClient(app) as tc:
        yield tc

    # Tear down the async engine so the next test builds a fresh one
    # against whatever env the next fixture sets.
    db_session_mod._engine.cache_clear()
    db_session_mod._sessionmaker.cache_clear()


# ---------------------------------------------------------------------------
# Dataset builder: creates one story with 2 articles (2 outlets), one
# with a full article_analysis row and one plain; plus a story_comparison
# row so the story-detail endpoint exercises every schema branch.
# ---------------------------------------------------------------------------
@pytest.fixture()
def api_dataset(db_session):
    now = datetime.now(tz=timezone.utc)

    outlet_a = Outlet(name="_test outlet API A",
                      slug="_test_api_o_a",
                      rss_url="https://x.example/_test_api_o_a",
                      website="https://x.example",
                      active=True)
    outlet_b = Outlet(name="_test outlet API B",
                      slug="_test_api_o_b",
                      rss_url="https://x.example/_test_api_o_b",
                      website="https://x.example",
                      active=True)
    db_session.add_all([outlet_a, outlet_b])
    db_session.flush()

    story = Story(title="_dbg_ api story about the union budget",
                  topic="budget",
                  first_seen_at=now - timedelta(hours=6),
                  last_seen_at=now,
                  article_count=2,
                  summary="Two outlets covered the same story.")
    db_session.add(story)
    db_session.flush()

    enrich_run = AnalysisRun(
        ran_at=now, model_id="test-enrich-model",
        prompt_version="enrich_v1", purpose="enrich",
    )
    compare_run = AnalysisRun(
        ran_at=now, model_id="test-compare-model",
        prompt_version="compare_v1", purpose="compare",
    )
    db_session.add_all([enrich_run, compare_run])
    db_session.flush()

    art_a = Article(
        outlet_id=outlet_a.id,
        url="_test_api_url_a",
        headline="_test api article about union budget reforms",
        author="_test author A",
        published_at=now - timedelta(hours=4),
        full_text=("The union budget introduced tax reforms today. " * 12),
        processing_state="complete",
        story_id=story.id,
    )
    art_b = Article(
        outlet_id=outlet_b.id,
        url="_test_api_url_b",
        headline="_test api second article on budget tax",
        author=None,
        published_at=now - timedelta(hours=3),
        full_text=("Opposition critiqued the budget's tax reforms. " * 12),
        processing_state="complete",
        story_id=story.id,
    )
    db_session.add_all([art_a, art_b])
    db_session.flush()

    aa_a = ArticleAnalysis(
        article_id=art_a.id,
        analysis_run_id=enrich_run.id,
        framing_score=Decimal("-0.40"),
        framing_label="critical",
        framing_confidence=Decimal("0.75"),
        headline_sentiment=Decimal("-0.20"),
        body_sentiment=Decimal("-0.30"),
        key_themes=["budget", "tax reform"],
        entities={"people": ["FM"], "organizations": ["Ministry of Finance"],
                  "locations": [], "other": []},
        quoted_sources=[{"speaker": "FM", "affiliation": "government",
                         "quote": "This will fuel growth.", "stance": "supports"}],
        source_distribution={"government": 1, "opposition": 0, "expert": 0,
                             "civil_society": 0, "corporate": 0,
                             "unnamed_source": 0, "other": 0},
        evidence_snippets=["critics said the measures would hurt"],
    )
    aa_b = ArticleAnalysis(
        article_id=art_b.id,
        analysis_run_id=enrich_run.id,
        framing_score=Decimal("0.30"),
        framing_label="supportive",
        framing_confidence=Decimal("0.65"),
        headline_sentiment=Decimal("0.10"),
        body_sentiment=Decimal("0.20"),
        key_themes=["budget", "growth"],
        entities={"people": [], "organizations": [],
                  "locations": [], "other": []},
        quoted_sources=[],
        source_distribution={"government": 0, "opposition": 0, "expert": 0,
                             "civil_society": 0, "corporate": 0,
                             "unnamed_source": 0, "other": 0},
        evidence_snippets=["the announcement supports investment"],
    )
    db_session.add_all([aa_a, aa_b])
    db_session.flush()

    sc = StoryComparison(
        story_id=story.id,
        analysis_run_id=compare_run.id,
        differences=("- outlet A led with the critical angle.\n"
                     "- outlet B highlighted the supportive framing."),
        framing_spread=Decimal("0.35"),
        coverage_matrix={
            outlet_a.slug: {"budget": 0.9, "tax reform": 0.8, "growth": 0.2},
            outlet_b.slug: {"budget": 0.7, "tax reform": 0.4, "growth": 0.9},
        },
        not_present_here={
            outlet_a.slug: ["growth angle"],
            outlet_b.slug: ["opposition critique"],
        },
    )
    db_session.add(sc)
    db_session.commit()

    return {
        "outlet_a": outlet_a, "outlet_b": outlet_b,
        "story":    story,
        "art_a":    art_a,    "art_b":    art_b,
        "sc":       sc,
    }


# =============================================================================
# HEALTH — preserved
# =============================================================================
def test_health_endpoint(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# =============================================================================
# OVERVIEW
# =============================================================================
def test_overview_returns_counts_and_disclaimer(api_client, api_dataset):
    r = api_client.get("/overview")
    assert r.status_code == 200
    j = r.json()

    # Schema keys
    assert set(j).issuperset({
        "article_count", "story_count", "active_outlet_count",
        "articles_by_state", "articles_last_24h", "stories_last_24h",
        "latest_ingestion_run", "framing_distribution",
        "framing_disclaimer",
    })

    # Our test dataset contributes ≥ 2 articles, ≥ 1 story, ≥ 2 outlets
    assert j["article_count"]       >= 2
    assert j["story_count"]         >= 1
    assert j["active_outlet_count"] >= 2

    # Framing disclaimer preserved verbatim
    assert "framing indicator" in j["framing_disclaimer"].lower()
    assert "outlet" in j["framing_disclaimer"].lower()

    # articles_by_state should include 'complete' (from our fixture) and
    # values must be integers
    assert isinstance(j["articles_by_state"], dict)
    for state, count in j["articles_by_state"].items():
        assert isinstance(state, str)
        assert isinstance(count, int)


# =============================================================================
# STORIES — list + detail
# =============================================================================
def test_stories_list_paginated(api_client, api_dataset):
    r = api_client.get("/stories?page=1&limit=5")
    assert r.status_code == 200
    j = r.json()
    assert j["page"] == 1
    assert j["limit"] == 5
    assert j["total"] >= 1
    assert isinstance(j["items"], list)
    assert len(j["items"]) <= 5

    # Our test story should be reachable in the first few pages ordered
    # by last_seen_at DESC (we set last_seen_at=now).
    found = any(
        item["id"] == api_dataset["story"].id for item in j["items"]
    )
    if not found:
        # Fallback: search a bit deeper — 20 pages of 5 = 100 latest,
        # which is well above what a shared test DB usually holds.
        for page in range(2, 6):
            r2 = api_client.get(f"/stories?page={page}&limit=5")
            found = any(
                it["id"] == api_dataset["story"].id for it in r2.json()["items"]
            )
            if found:
                break
    assert found, "test story should be in a recent page of /stories"


def test_stories_list_rejects_bad_pagination(api_client):
    r = api_client.get("/stories?page=0&limit=5")
    assert r.status_code == 422
    r = api_client.get("/stories?page=1&limit=0")
    assert r.status_code == 422
    r = api_client.get("/stories?page=1&limit=9999")
    assert r.status_code == 422


def test_story_detail_returns_full_payload(api_client, api_dataset):
    sid = api_dataset["story"].id
    r = api_client.get(f"/stories/{sid}")
    assert r.status_code == 200
    j = r.json()

    assert j["id"] == sid
    assert j["title"] == api_dataset["story"].title
    assert j["article_count"] == 2
    assert set(j["outlet_slugs"]) == {
        api_dataset["outlet_a"].slug,
        api_dataset["outlet_b"].slug,
    }

    # Articles with analyses
    assert len(j["articles"]) == 2
    for art in j["articles"]:
        assert "outlet" in art and "slug" in art["outlet"]
        assert "analysis" in art
        assert art["analysis"] is not None
        assert -1.0 <= art["analysis"]["framing_score"] <= 1.0
        assert art["analysis"]["framing_label"] in (
            "critical", "neutral", "supportive", "mixed", "insufficient"
        )
        # quoted_sources preserved verbatim (list)
        assert isinstance(art["analysis"]["quoted_sources"], list)
        assert isinstance(art["analysis"]["evidence_snippets"], list)

    # Comparison payload
    assert j["comparison"] is not None
    assert j["comparison"]["differences"].startswith("-")
    assert 0.0 <= j["comparison"]["framing_spread"] <= 2.0
    assert isinstance(j["comparison"]["coverage_matrix"], dict)
    assert isinstance(j["comparison"]["not_present_here"], dict)

    # Framing disclaimer
    assert "framing indicator" in j["framing_disclaimer"].lower()


def test_story_detail_returns_404_when_missing(api_client):
    r = api_client.get("/stories/999999999")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


# =============================================================================
# ARTICLES — detail
# =============================================================================
def test_article_detail(api_client, api_dataset):
    aid = api_dataset["art_a"].id
    r = api_client.get(f"/articles/{aid}")
    assert r.status_code == 200
    j = r.json()
    assert j["id"] == aid
    assert j["outlet"]["slug"] == api_dataset["outlet_a"].slug
    assert j["story_id"] == api_dataset["story"].id
    assert j["full_text_available"] is True
    assert j["analysis"] is not None
    # Body text must NOT be in the response — we only expose availability
    assert "full_text" not in j


def test_article_detail_404(api_client):
    r = api_client.get("/articles/999999999")
    assert r.status_code == 404


# =============================================================================
# OUTLETS
# =============================================================================
def test_list_outlets_includes_test_outlets(api_client, api_dataset):
    r = api_client.get("/outlets")
    assert r.status_code == 200
    slugs = [o["slug"] for o in r.json()]
    assert api_dataset["outlet_a"].slug in slugs
    assert api_dataset["outlet_b"].slug in slugs
    # No sensitive fields leaked
    for o in r.json():
        assert set(o.keys()).issubset(
            {"id", "name", "slug", "website", "logo_url"}
        )


def test_outlet_detail(api_client, api_dataset):
    r = api_client.get(f"/outlets/{api_dataset['outlet_a'].slug}")
    assert r.status_code == 200
    j = r.json()
    assert j["slug"] == api_dataset["outlet_a"].slug
    assert j["active"] is True
    assert "rss_url" in j


def test_outlet_detail_404(api_client):
    r = api_client.get("/outlets/_nonexistent_outlet_slug_zzz")
    assert r.status_code == 404


def test_outlet_stats_falls_back_when_view_empty(api_client, api_dataset):
    r = api_client.get(f"/outlets/{api_dataset['outlet_a'].slug}/stats")
    assert r.status_code == 200
    j = r.json()
    # The outlet_30d_stats view is refreshed daily; it may or may not
    # contain our fresh test outlet. Either way the endpoint returns 200
    # with a well-formed payload.
    assert j["slug"] == api_dataset["outlet_a"].slug
    assert isinstance(j["article_count"], int)
    assert "framing_disclaimer" in j


# =============================================================================
# SEARCH — Postgres FTS
# =============================================================================
def test_search_finds_test_article(api_client, api_dataset):
    r = api_client.get("/search?q=budget&limit=20")
    assert r.status_code == 200
    j = r.json()
    assert j["query"] == "budget"
    # Our fixture bodies contain 'budget' → at least our 2 test articles hit
    test_ids = {api_dataset["art_a"].id, api_dataset["art_b"].id}
    hit_ids = {h["article_id"] for h in j["items"]}
    assert test_ids.issubset(hit_ids), \
        f"expected {test_ids} in hits, got {hit_ids}"
    # Each hit carries a snippet
    for hit in j["items"]:
        if hit["article_id"] in test_ids:
            assert hit["snippet"]
            assert hit["rank"] >= 0.0


def test_search_rejects_short_query(api_client):
    r = api_client.get("/search?q=a")   # min_length=2 on the Query
    assert r.status_code == 422


def test_search_pagination_bounds(api_client):
    r = api_client.get("/search?q=budget&page=0")
    assert r.status_code == 422
    r = api_client.get("/search?q=budget&limit=9999")
    assert r.status_code == 422


# =============================================================================
# TRENDS
# =============================================================================
def test_trends_default_window(api_client, api_dataset):
    r = api_client.get("/trends")
    assert r.status_code == 200
    j = r.json()
    assert j["window_days"] == 7
    assert isinstance(j["articles_per_day"], list)
    assert isinstance(j["stories_per_day"], list)
    assert isinstance(j["framing_distribution"], list)
    for pt in j["articles_per_day"]:
        assert "date" in pt and "count" in pt
        assert isinstance(pt["count"], int)
    # Disclaimer preserved
    assert "framing indicator" in j["framing_disclaimer"].lower()


def test_trends_custom_window_binds_integer(api_client, api_dataset):
    """Regression guard: the window parameter must bind as an int and
    not be forced to text via string concatenation. Under asyncpg the
    old `(:days || ' days')::interval` pattern raised
    ``TypeError: expected str, got int`` because asyncpg would not
    auto-cast the parameter. This test asserts a non-default window
    returns 200 for several values."""
    for w in (1, 3, 14, 30, 90):
        r = api_client.get(f"/trends?window={w}")
        assert r.status_code == 200, (
            f"window={w} failed with status {r.status_code}: {r.text[:200]}"
        )
        assert r.json()["window_days"] == w


def test_trends_query_does_not_interpolate_window(api_client):
    """Static guard: source of the trends module must not concatenate
    ``window`` into the SQL string; it must be bound as a parameter."""
    import inspect
    from src.api import trends as trends_mod
    src = inspect.getsource(trends_mod)
    # Only the ``:days`` bind should carry the window into the SQL.
    assert ":days" in src
    # And no f-string / % / + splicing of `window` into the SQL text.
    assert "f'''" not in src and 'f"""' not in src
    assert "{window}" not in src
    assert "% window" not in src
    # No re-introduction of the broken pattern that asyncpg rejects.
    assert "|| ' days'" not in src
    assert '|| " days"' not in src


def test_trends_rejects_bad_window(api_client):
    r = api_client.get("/trends?window=0")
    assert r.status_code == 422
    r = api_client.get("/trends?window=1000")
    assert r.status_code == 422


# =============================================================================
# Framing semantics guard — the API must NEVER expose a political
# left/right label. This is a smoke test that scans a story-detail
# payload for forbidden vocabulary.
# =============================================================================
def test_no_political_labels_in_story_payload(api_client, api_dataset):
    r = api_client.get(f"/stories/{api_dataset['story'].id}")
    assert r.status_code == 200
    body = r.text.lower()
    for forbidden in ("left-wing", "right-wing"):
        # We only check obviously political classifier vocabulary in the
        # response body. The comparison text can mention "left" as an
        # ordinary word — that's not a violation.
        assert forbidden not in body
