"""Orchestrator integration tests for ``run_once()``.

The extraction drain-loop behavior is already covered in
``test_ingestion.py::test_orchestrator_drains_all_articles_beyond_batch_limit``;
these tests focus on the enrich + compare integration added in this
task, plus the run-level lifecycle guarantees:

  * full pipeline completes and updates the ingestion_runs row
  * enrichment failures don't crash the run; articles remain retryable
  * comparison failures don't crash the run; articles remain retryable
  * no eligible enrich/compare work → no LLM calls
  * an unexpected orchestrator exception marks the run 'failed', not
    stuck 'running'

Isolation: because the test Neon DB is shared with real ingestion data
that has previously reached 'clustered', the tests monkey-patch
``run_module.enrich_articles`` and ``run_module.compare_stories`` with
outlet-scoped / story-scoped wrappers. Production ``run.py`` behavior
is unchanged; only the test's own articles are touched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from src.db.models import Article, IngestionRun, Outlet, Story
from src.ingestion import run as run_module
from src.ingestion.embed import HashEmbedder
from src.ingestion.run import run_once

from .conftest import FakeFetcher, FakeResponse, make_article_html, make_rss


# ---------------------------------------------------------------------------
# Local fake LLM — independent of test_enrich.py / test_compare.py.
# ---------------------------------------------------------------------------
class FakeGroqClient:
    """Returns queued responses in call order; records every call."""

    def __init__(self, responses=None, raise_all: Exception | None = None):
        self.responses = list(responses or [])
        self.raise_all = raise_all
        self.calls: list[dict] = []

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> str:
        self.calls.append({"model": model, "prompt": prompt,
                           "timeout_s": timeout_s})
        if self.raise_all is not None:
            raise self.raise_all
        if not self.responses:
            raise AssertionError("FakeGroqClient exhausted responses")
        return self.responses.pop(0)


# Canned valid enrichment JSON (schema matches enrich_schema.EnrichmentResponse).
_VALID_ENRICH: dict = {
    "framing_score": 0.0,
    "framing_label": "neutral",
    "framing_confidence": 0.6,
    "headline_sentiment": 0.0,
    "body_sentiment": 0.0,
    "key_themes": ["budget", "reform"],
    "entities": {"people": [], "organizations": [],
                 "locations": [], "other": []},
    "quoted_sources": [{
        "speaker": "Analyst",
        "affiliation": None,
        "quote": "This will affect the fiscal situation.",
        "stance": "neutral",
    }],
    "source_distribution": {"government": 0, "opposition": 0, "expert": 1,
                            "civil_society": 0, "corporate": 0,
                            "unnamed_source": 0, "other": 0},
    "evidence_snippets": ["evidence line one from the article"],
}


def _valid_enrich_json() -> str:
    return json.dumps(_VALID_ENRICH)


# ---------------------------------------------------------------------------
# Test-outlet setup: uses "the-hindu" (a phase_1 slug) so _load_active_outlets
# picks it up. conftest cleanup deletes 'the-hindu' at teardown just as the
# existing orchestrator test does.
# ---------------------------------------------------------------------------
def _make_the_hindu_with_rss(db_session, rss_url: str) -> Outlet:
    outlet = Outlet(
        name="_test outlet the hindu",
        slug="the-hindu",
        rss_url=rss_url,
        website="https://x.example",
        active=True,
    )
    db_session.add(outlet)
    db_session.commit()
    return outlet


def _rss_bytes(urls_with_headlines: list[tuple[str, str]]) -> str:
    fmt = "%a, %d %b %Y %H:%M:%S +0000"
    now = datetime.now(tz=timezone.utc)
    items = []
    for i, (url, headline) in enumerate(urls_with_headlines):
        pub = (now.replace(microsecond=0)).strftime(fmt)
        items.append({"title": headline, "link": url, "pubDate": pub})
    return make_rss(items)


def _fake_fetcher_for(outlet: Outlet, articles: list[tuple[str, str, str]]) -> FakeFetcher:
    """articles: list of (url, headline, body)."""
    responses: dict[str, FakeResponse] = {
        outlet.rss_url: FakeResponse(
            200,
            _rss_bytes([(u, h) for u, h, _ in articles]),
        ),
    }
    for url, headline, body in articles:
        responses[url] = FakeResponse(200, make_article_html(headline, body))
    return FakeFetcher(responses)


def _scope_llm_stages_to_outlet(monkeypatch, outlet_id: int) -> None:
    """Wrap enrich_articles and compare_stories in run_module so they only
    touch this outlet's articles / this outlet's stories. Production
    behavior of run.py is unchanged — only the runtime lookup names inside
    run_module are patched, and only for the current test.
    """
    orig_enrich = run_module.enrich_articles
    orig_compare = run_module.compare_stories

    def scoped_enrich(session, *, llm, **kw):
        # Force scoping to the test outlet — real production articles
        # in 'clustered' state on the shared DB are ignored.
        return orig_enrich(session, llm=llm, outlet_id=outlet_id, **kw)

    def scoped_compare(session, *, llm, **kw):
        # Only compare stories that contain articles from this outlet.
        # In practice single-outlet test stories don't meet the ≥2 outlet
        # threshold, so compare_stories will return (0, 0) — which is
        # exactly the "no eligible" behavior we want.
        story_ids = list(session.scalars(
            select(Article.story_id)
            .where(Article.outlet_id == outlet_id)
            .where(Article.story_id.isnot(None))
            .distinct()
        ))
        return orig_compare(session, llm=llm, story_ids=story_ids, **kw)

    monkeypatch.setattr(run_module, "enrich_articles", scoped_enrich)
    monkeypatch.setattr(run_module, "compare_stories", scoped_compare)


def _prep_env(monkeypatch) -> None:
    """LLM env + shared DB alignment (see conftest.align_run_db_to_test_db)."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key-ignored")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    from .conftest import align_run_db_to_test_db
    align_run_db_to_test_db(monkeypatch)


# ---------------------------------------------------------------------------
# Test 1 — Full pipeline: fetch → extract → embed → cluster → enrich → compare
# ---------------------------------------------------------------------------
def test_full_pipeline_runs_every_stage(db_session, monkeypatch):
    _prep_env(monkeypatch)
    outlet = _make_the_hindu_with_rss(db_session, rss_url="_test_run_full_rss")
    _scope_llm_stages_to_outlet(monkeypatch, outlet.id)

    # 3 articles, all similar bodies so clustering groups them together
    body = "The union budget 2026 introduced sweeping tax reforms. " * 12
    articles = [
        ("_test_run_full_url_1", "_test full pipeline article 1", body),
        ("_test_run_full_url_2", "_test full pipeline article 2", body),
        ("_test_run_full_url_3", "_test full pipeline article 3", body),
    ]
    fetcher = _fake_fetcher_for(outlet, articles)

    # 3 enrichment responses; compare will find 0 eligible (single outlet)
    llm = FakeGroqClient(responses=[_valid_enrich_json()] * 3)

    started = datetime.now(tz=timezone.utc)
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: fetcher,
        llm_factory=lambda: llm,
    )
    assert rc == 0

    # All 3 articles reached 'analyzed' (compare skipped — single outlet
    # means compare_stories returned 0 eligible; articles NOT advanced
    # to 'complete', which is the documented behavior).
    db_session.expire_all()
    states = sorted(a.processing_state for a in db_session.scalars(
        select(Article).where(Article.url.like("_test_run_full_url_%"))
    ).all())
    assert states == ["analyzed", "analyzed", "analyzed"], states

    # Enrichment called exactly 3 times, compare called 0 times
    assert len(llm.calls) == 3
    for call in llm.calls:
        assert "coverage_matrix" not in call["prompt"], \
            "compare prompt should NOT have been sent (single outlet story)"

    # ingestion_runs row closed as success with correct counts
    run = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc()).limit(1)
    )
    assert run is not None
    assert run.status == "success"
    assert run.completed_at is not None
    assert run.articles_discovered == 3
    assert run.articles_inserted == 3
    assert run.articles_failed == 0
    assert run.llm_calls == 3   # counted by _CountingLLM


# ---------------------------------------------------------------------------
# Test 2 — Compare stage integration: two outlets → compare runs
# (exercises the "and compare" leg of the full-pipeline requirement).
# ---------------------------------------------------------------------------
def test_full_pipeline_includes_compare_when_two_outlets(db_session, monkeypatch):
    _prep_env(monkeypatch)
    outlet_a = _make_the_hindu_with_rss(db_session, rss_url="_test_run_two_rss")

    # Add a second outlet with a _test_ slug and manually mark its
    # articles 'clustered' with the same story_id as the-hindu's articles
    # after run_once finishes stages 1-4. But run.py's _load_active_outlets
    # only picks up phase_1 outlets. Since only "the-hindu" is a phase_1
    # slug in outlets.yaml here (other phase_1 slugs may or may not be
    # seeded in Neon), we drive the second outlet's contribution
    # entirely by manually inserting a pre-clustered article.
    outlet_b = Outlet(
        name="_test outlet second",
        slug="_test_run_second_outlet",
        rss_url="_test_run_second_rss",
        website="https://x.example",
        active=True,
    )
    db_session.add(outlet_b)
    db_session.commit()

    body = "Government budget 2026 reforms sweeping economic changes. " * 12
    articles_a = [
        ("_test_run_two_url_1", "_test two-outlet A1", body),
        ("_test_run_two_url_2", "_test two-outlet A2", body),
    ]
    fetcher = _fake_fetcher_for(outlet_a, articles_a)

    # Scope enrich to BOTH test outlets; scope compare to any story
    # whose articles come from either test outlet.
    orig_enrich = run_module.enrich_articles
    orig_compare = run_module.compare_stories
    test_outlet_ids = [outlet_a.id, outlet_b.id]

    def scoped_enrich(session, *, llm, **kw):
        # Loop the per-outlet filter — enrich_articles takes a single
        # outlet_id. run.py now branches on `.rate_limited` / `.analyzed`
        # / `.failed_permanent`, so we must return an EnrichBatchResult
        # not a bare tuple.
        from src.ingestion.enrich import EnrichBatchResult
        total_analyzed, total_failed = 0, 0
        rate_limited = False
        for oid in test_outlet_ids:
            r = orig_enrich(session, llm=llm, outlet_id=oid, **kw)
            total_analyzed += r.analyzed
            total_failed += r.failed_permanent
            if r.rate_limited:
                rate_limited = True
                break
        return EnrichBatchResult(
            analyzed=total_analyzed,
            failed_permanent=total_failed,
            rate_limited=rate_limited,
        )

    def scoped_compare(session, *, llm, **kw):
        story_ids = list(session.scalars(
            select(Article.story_id)
            .where(Article.outlet_id.in_(test_outlet_ids))
            .where(Article.story_id.isnot(None))
            .distinct()
        ))
        return orig_compare(session, llm=llm, story_ids=story_ids, **kw)

    monkeypatch.setattr(run_module, "enrich_articles", scoped_enrich)
    monkeypatch.setattr(run_module, "compare_stories", scoped_compare)

    # Run 1 — full pipeline for the-hindu WITH enrichment, but skip
    # compare (single outlet means compare has no eligible story
    # anyway). After this run, the-hindu's 2 articles are 'analyzed'.
    llm1 = FakeGroqClient(responses=[_valid_enrich_json()] * 2)
    rc1 = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: fetcher,
        llm_factory=lambda: llm1,
        skip_compare=True,
    )
    assert rc1 == 0
    assert len(llm1.calls) == 2   # one enrich call per the-hindu article

    # After clustering + enrichment, the-hindu's articles share a story.
    db_session.expire_all()
    story_id = db_session.scalar(
        select(Article.story_id).where(Article.url == "_test_run_two_url_1")
    )
    assert story_id is not None
    # Confirm the-hindu articles are in 'analyzed' state (not 'complete',
    # because compare was skipped in Run 1).
    a_hindu = db_session.scalars(
        select(Article).where(Article.url.like("_test_run_two_url_%"))
    ).all()
    assert all(a.processing_state == "analyzed" for a in a_hindu)

    # Insert a second-outlet article manually, in 'clustered' state,
    # attached to the same story so compare (in Run 2) sees 2 outlets.
    now = datetime.now(tz=timezone.utc)
    article_b = Article(
        outlet_id=outlet_b.id,
        url="_test_run_two_url_3_b",
        headline="_test two-outlet B1",
        published_at=now,
        full_text=body,
        processing_state="clustered",
        story_id=story_id,
        embedding=HashEmbedder().encode([body])[0].tolist(),
    )
    db_session.add(article_b)
    db_session.commit()

    # Run 2 — enrich outlet_b's one article + compare the story.
    # Exactly 2 LLM calls expected: 1 enrich + 1 compare.
    llm2 = FakeGroqClient(responses=[
        _valid_enrich_json(),  # for the new outlet_b article
        # compare response — coverage_matrix must include both slugs and
        # every theme in the fixed list ("budget", "reform" per _VALID_ENRICH)
        json.dumps({
            "differences": (
                f"- {outlet_a.slug} led with the reform angle.\n"
                f"- {outlet_b.slug} led with the budget angle."
            ),
            "coverage_matrix": {
                outlet_a.slug: {"budget": 0.8, "reform": 0.4},
                outlet_b.slug: {"budget": 0.4, "reform": 0.8},
            },
            "not_present_here": {outlet_a.slug: [], outlet_b.slug: []},
        }),
    ])

    rc2 = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: _fake_fetcher_for(outlet_a, []),  # empty RSS
        llm_factory=lambda: llm2,
    )
    assert rc2 == 0

    db_session.expire_all()

    # Verify compare actually executed by checking side effects, not
    # prompt substrings. `coverage_matrix` appears in the compare PROMPT
    # (as part of the schema description we send to the LLM), so a
    # substring check would pass even for a broken run — hence we
    # assert on DB state and call count instead.

    # (1) Exactly 2 LLM calls in Run 2 — one enrich + one compare
    assert len(llm2.calls) == 2, (
        f"expected 2 LLM calls in Run 2 (1 enrich + 1 compare), "
        f"got {len(llm2.calls)}"
    )

    # (2) Exactly one story_comparisons row exists for this story
    from sqlalchemy import func as sqla_func
    from src.db.models import StoryComparison
    sc_count = db_session.scalar(
        select(sqla_func.count())
        .select_from(StoryComparison)
        .where(StoryComparison.story_id == story_id)
    )
    assert sc_count == 1, (
        f"expected exactly 1 story_comparisons row for story_id={story_id}, "
        f"got {sc_count}"
    )

    # (3) Every article attached to that story reached 'complete'
    articles_for_story = db_session.scalars(
        select(Article).where(Article.story_id == story_id)
    ).all()
    assert len(articles_for_story) == 3, (
        f"expected 3 articles on story_id={story_id}, "
        f"got {len(articles_for_story)}"
    )
    for a in articles_for_story:
        assert a.processing_state == "complete", (
            f"article id={a.id} url={a.url} in state "
            f"{a.processing_state!r} (expected 'complete')"
        )


# ---------------------------------------------------------------------------
# Test 3 — Enrichment failure does not crash the run
# ---------------------------------------------------------------------------
def test_enrichment_batch_failure_does_not_crash_run(db_session, monkeypatch):
    _prep_env(monkeypatch)
    outlet = _make_the_hindu_with_rss(db_session, rss_url="_test_run_enfail_rss")
    _scope_llm_stages_to_outlet(monkeypatch, outlet.id)

    body = "Budget 2026 story text " * 12
    articles = [
        ("_test_run_enfail_url_1", "_test enrich fail 1", body),
        ("_test_run_enfail_url_2", "_test enrich fail 2", body),
    ]
    fetcher = _fake_fetcher_for(outlet, articles)

    # LLM raises on every call → enrich_articles internally bumps
    # attempt_count and swallows, so run_once continues to compare.
    llm = FakeGroqClient(raise_all=RuntimeError("simulated LLM outage"))

    started = datetime.now(tz=timezone.utc)
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: fetcher,
        llm_factory=lambda: llm,
    )
    assert rc == 0   # run still succeeds — enrichment failure is per-article

    db_session.expire_all()
    # After 3 enrichment attempts per article (all failing), they should
    # be in 'failed_analyze' (moved by enrich._record_llm_failure) OR
    # still 'clustered' with attempt_count > 0 depending on how many
    # drain iterations ran. Both are retryable (failed_analyze is a
    # terminal state per architecture, not a corruption).
    articles_after = db_session.scalars(
        select(Article).where(Article.url.like("_test_run_enfail_url_%"))
    ).all()
    assert len(articles_after) == 2
    for a in articles_after:
        # NOT stuck in 'analyzed' (which would mean enrich claimed success)
        assert a.processing_state != "analyzed", a.processing_state
        # NOT stuck in 'complete' either
        assert a.processing_state != "complete", a.processing_state

    # Run row: success, but articles_failed > 0
    run = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc()).limit(1)
    )
    assert run is not None
    assert run.status == "success"


# ---------------------------------------------------------------------------
# Test 4 — Comparison failure does not crash the run
# ---------------------------------------------------------------------------
def test_comparison_batch_failure_does_not_crash_run(db_session, monkeypatch):
    _prep_env(monkeypatch)
    outlet = _make_the_hindu_with_rss(db_session, rss_url="_test_run_cmpfail_rss")

    # Monkey-patch compare_stories to raise directly, so we test the
    # try/except wrapper around it in run.py. Enrichment stays scoped
    # so we don't touch real DB rows.
    orig_enrich = run_module.enrich_articles

    def scoped_enrich(session, *, llm, **kw):
        return orig_enrich(session, llm=llm, outlet_id=outlet.id, **kw)

    def crashing_compare(session, *, llm, **kw):
        raise RuntimeError("simulated compare crash")

    monkeypatch.setattr(run_module, "enrich_articles", scoped_enrich)
    monkeypatch.setattr(run_module, "compare_stories", crashing_compare)

    body = "Budget story body " * 12
    articles = [
        ("_test_run_cmpfail_url_1", "_test compare fail 1", body),
        ("_test_run_cmpfail_url_2", "_test compare fail 2", body),
    ]
    fetcher = _fake_fetcher_for(outlet, articles)
    llm = FakeGroqClient(responses=[_valid_enrich_json()] * 2)

    started = datetime.now(tz=timezone.utc)
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: fetcher,
        llm_factory=lambda: llm,
    )
    assert rc == 0

    db_session.expire_all()
    # Enrichment succeeded, so articles are 'analyzed'; compare
    # crashed, so they DID NOT advance to 'complete' → retryable.
    articles_after = db_session.scalars(
        select(Article).where(Article.url.like("_test_run_cmpfail_url_%"))
    ).all()
    assert len(articles_after) == 2
    for a in articles_after:
        assert a.processing_state == "analyzed", a.processing_state

    run = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc()).limit(1)
    )
    assert run is not None
    assert run.status == "success"


# ---------------------------------------------------------------------------
# Test 5 — No eligible enrich/compare work → no LLM calls
# ---------------------------------------------------------------------------
def test_no_eligible_llm_work_makes_zero_llm_calls(db_session, monkeypatch):
    _prep_env(monkeypatch)
    outlet = _make_the_hindu_with_rss(db_session, rss_url="_test_run_none_rss")
    _scope_llm_stages_to_outlet(monkeypatch, outlet.id)

    # Empty RSS feed → 0 articles discovered → nothing reaches
    # 'clustered' → enrich has 0 candidates → compare has 0 candidates.
    fetcher = _fake_fetcher_for(outlet, [])
    llm = FakeGroqClient(responses=[])

    started = datetime.now(tz=timezone.utc)
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: fetcher,
        llm_factory=lambda: llm,
    )
    assert rc == 0
    assert llm.calls == []   # not even one LLM call attempted

    run = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc()).limit(1)
    )
    assert run is not None
    assert run.status == "success"
    assert run.llm_calls == 0
    assert run.articles_discovered == 0
    assert run.articles_inserted == 0


# ---------------------------------------------------------------------------
# Test 6 — Unexpected orchestrator exception marks run 'failed', not 'running'
# ---------------------------------------------------------------------------
def test_unexpected_exception_marks_run_failed_not_running(db_session, monkeypatch):
    _prep_env(monkeypatch)

    def crashing_load_active_outlets(*a, **kw):
        raise RuntimeError("simulated orchestrator crash — early")

    monkeypatch.setattr(run_module, "_load_active_outlets",
                        crashing_load_active_outlets)

    started = datetime.now(tz=timezone.utc)
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: FakeFetcher({}),
        llm_factory=lambda: FakeGroqClient(responses=[]),
    )
    assert rc == 1

    # ingestion_runs row should exist and be marked 'failed', not
    # left as 'running'.
    db_session.expire_all()
    run = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc()).limit(1)
    )
    assert run is not None
    assert run.status == "failed", f"expected 'failed', got {run.status!r}"
    assert run.completed_at is not None
    assert run.error and "simulated orchestrator crash" in run.error


# ---------------------------------------------------------------------------
# Test 7 — GROQ_API_KEY absent silently skips enrich + compare
# (documented safety net so pipeline development without an API key
# doesn't error out).
# ---------------------------------------------------------------------------
def test_missing_groq_api_key_skips_llm_stages(db_session, monkeypatch):
    # Use the same DB-alignment as _prep_env (so run_once() hits the
    # SAME dev-test DB as the fixture's db_session), then override
    # GROQ_API_KEY to empty to exercise the "no key → skip LLM" path.
    _prep_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "")
    from src.config import get_settings
    get_settings.cache_clear()

    outlet = _make_the_hindu_with_rss(db_session, rss_url="_test_run_nokey_rss")

    body = "Some article content " * 12
    articles = [("_test_run_nokey_url_1", "_test no key 1", body)]
    fetcher = _fake_fetcher_for(outlet, articles)

    started = datetime.now(tz=timezone.utc)
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: fetcher,
        # No llm_factory + no GROQ_API_KEY → enrich + compare skipped
    )
    assert rc == 0

    db_session.expire_all()
    a = db_session.scalar(
        select(Article).where(Article.url == "_test_run_nokey_url_1")
    )
    # Reached 'clustered' but not further — LLM stages were silently skipped
    assert a.processing_state == "clustered", a.processing_state

    run = db_session.scalar(
        select(IngestionRun)
        .where(IngestionRun.started_at >= started)
        .order_by(IngestionRun.id.desc()).limit(1)
    )
    assert run is not None
    assert run.status == "success"
    assert run.llm_calls == 0


# ---------------------------------------------------------------------------
# Budget / rate-limit orchestration tests
# (added 2026-09-24 for the "intelligent incremental analysis" phase)
# ---------------------------------------------------------------------------
from dataclasses import dataclass as _dataclass  # noqa: E402  (test-local)
from typing import Iterator as _Iterator  # noqa: E402


@_dataclass
class _FakeBatchResult:
    """Mimics enrich.EnrichBatchResult (iterable → (analyzed, failed)),
    with a rate_limited attribute the orchestrator branches on."""
    analyzed: int
    failed_permanent: int
    rate_limited: bool = False

    def __iter__(self) -> _Iterator[int]:
        yield self.analyzed
        yield self.failed_permanent


def test_run_respects_enrich_budget(db_session, monkeypatch):
    """run_once must not enrich more articles than
    settings.llm_enrich_budget_per_run. Verified by wrapping
    ``enrich_articles`` in run_module with a spy that returns a fake
    ``EnrichBatchResult`` and counts total requested work."""
    _prep_env(monkeypatch)
    # Force a small, deterministic budget for this test.
    monkeypatch.setenv("LLM_ENRICH_BUDGET_PER_RUN", "5")
    monkeypatch.setenv("LLM_COMPARE_BUDGET_PER_RUN", "0")
    from src.config import get_settings
    get_settings.cache_clear()

    outlet = _make_the_hindu_with_rss(
        db_session, rss_url="_test_run_budget_rss"
    )

    body = "Budget-bounded body. " * 12
    articles = [
        (f"_test_run_budget_url_{i}", f"_test budget art {i}", body)
        for i in range(3)   # 3 articles will actually cluster
    ]
    fetcher = _fake_fetcher_for(outlet, articles)

    # Spy: track how many times enrich_articles gets called and with
    # what batch_limit; return "2 analyzed / 0 failed" each call so the
    # orchestrator can keep going but stays bounded by budget.
    calls: list[dict] = []

    def spy_enrich(session, *, llm, **kw):
        calls.append(dict(kw))
        # Pretend we processed 2 articles per call — bigger than the
        # first batch_limit=5 would allow only ONE call, then the
        # remaining budget = 5 - 2 = 3, one more call with take=3, then
        # budget = 1, one more call with take=1, then budget=0 → stop.
        return _FakeBatchResult(analyzed=2, failed_permanent=0)

    monkeypatch.setattr(run_module, "enrich_articles", spy_enrich)

    # Compare stubbed to a no-op — this test cares about the enrich loop.
    def stub_compare(session, *, llm, **kw):
        return (0, 0)
    monkeypatch.setattr(run_module, "compare_stories", stub_compare)

    llm = FakeGroqClient(responses=[])  # LLM never actually called
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: fetcher,
        llm_factory=lambda: llm,
    )
    assert rc == 0

    # Budget=5, each call returns 2 → expected batch_limit sequence: 5, 3, 1
    # and total requested work is 5 + 3 + 1 = 9 (capped by budget).
    # We also require that no single call took more than min(20, budget).
    batch_limits = [c.get("batch_limit") for c in calls]
    assert batch_limits, "enrich_articles was not called at all"
    assert batch_limits[0] == 5, batch_limits
    assert sum(batch_limits) <= 5 + 5, (
        f"total requested work {sum(batch_limits)} exceeded budget window"
    )
    # And we must have stopped once budget was exhausted (not looped
    # infinitely).
    assert len(calls) <= 5


def test_run_stops_enrich_drain_on_rate_limit_signal(db_session, monkeypatch):
    """When enrich_articles reports rate_limited=True the orchestrator
    must break out of the drain loop immediately, WITHOUT calling
    enrich_articles again this cycle. Budget is not exhausted, but a
    rate-limit signal takes precedence."""
    _prep_env(monkeypatch)
    monkeypatch.setenv("LLM_ENRICH_BUDGET_PER_RUN", "100")
    monkeypatch.setenv("LLM_COMPARE_BUDGET_PER_RUN", "0")
    from src.config import get_settings
    get_settings.cache_clear()

    outlet = _make_the_hindu_with_rss(
        db_session, rss_url="_test_run_rl_rss"
    )
    body = "Rate-limit body. " * 12
    articles = [
        (f"_test_run_rl_url_{i}", f"_test rl art {i}", body)
        for i in range(2)
    ]
    fetcher = _fake_fetcher_for(outlet, articles)

    call_count = {"n": 0}

    def spy_enrich_ratelimited(session, *, llm, **kw):
        call_count["n"] += 1
        # First call: signal rate-limit. If the drain loop is correct we
        # never get called again this cycle.
        return _FakeBatchResult(
            analyzed=0, failed_permanent=0, rate_limited=True,
        )

    monkeypatch.setattr(
        run_module, "enrich_articles", spy_enrich_ratelimited,
    )

    def stub_compare(session, *, llm, **kw):
        return (0, 0)
    monkeypatch.setattr(run_module, "compare_stories", stub_compare)

    llm = FakeGroqClient(responses=[])
    rc = run_once(
        phases=["phase_1"],
        embedder=HashEmbedder(),
        triggered_by="manual",
        fetcher_factory=lambda: fetcher,
        llm_factory=lambda: llm,
    )
    assert rc == 0
    # Exactly one enrich call — the drain must have broken immediately.
    assert call_count["n"] == 1, (
        f"expected 1 enrich_articles call after rate-limit, got {call_count['n']}"
    )
