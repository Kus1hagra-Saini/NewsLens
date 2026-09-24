"""Tests for the enrichment stage.

Uses a ``FakeGroqClient`` injected via the ``LLMClient`` protocol so
tests never make real API calls. Covers:

  * successful enrichment persists article_analysis + analysis_runs
  * article advances clustered → analyzed
  * quoted_sources and evidence_snippets are stored verbatim
  * malformed JSON leaves the article retryable (still 'clustered')
  * out-of-range score is rejected (ValidationError) → still retryable
  * three failures transition to 'failed_analyze'
  * once in 'failed_analyze' the article is NOT re-attempted
  * the analysis_runs row records the correct model_id + prompt_version
  * no candidates → no LLM call, no run row
  * re-enrichment overwrites the previous article_analysis row (latest-wins)
  * no real Groq/HTTP call happens (asserted by using FakeGroqClient)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy import update as sqla_update

from src.db.models import AnalysisRun, Article, ArticleAnalysis, Outlet, Story
from src.ingestion.enrich import (
    DEFAULT_PROMPT_VERSION,
    MAX_ATTEMPTS,
    enrich_articles,
)


# ---------------------------------------------------------------------------
# Fake LLM client — injected via the LLMClient Protocol
# ---------------------------------------------------------------------------
class FakeGroqClient:
    """Minimal LLMClient stub. Returns queued responses or raises queued exceptions."""

    def __init__(
        self,
        responses: list[str] | None = None,
        raise_for: list[Exception | None] | None = None,
    ):
        self.responses = list(responses or [])
        self.raise_for = list(raise_for or [])
        self.calls: list[dict] = []

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> str:
        self.calls.append(
            {"model": model, "prompt": prompt, "timeout_s": timeout_s}
        )
        if self.raise_for:
            exc = self.raise_for.pop(0)
            if exc is not None:
                raise exc
        if not self.responses:
            raise AssertionError("FakeGroqClient exhausted responses")
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# Sample response — the "happy path" LLM output
# ---------------------------------------------------------------------------
VALID_RESPONSE: dict = {
    "framing_score": -0.5,
    "framing_label": "critical",
    "framing_confidence": 0.8,
    "headline_sentiment": -0.4,
    "body_sentiment": -0.3,
    "key_themes": ["budget", "tax reform"],
    "entities": {
        "people": ["Nirmala Sitharaman"],
        "organizations": ["Ministry of Finance"],
        "locations": ["New Delhi"],
        "other": [],
    },
    "quoted_sources": [
        {
            "speaker": "Nirmala Sitharaman",
            "affiliation": "Finance Minister",
            "quote": "This budget will fuel long-term growth.",
            "stance": "supports",
        }
    ],
    "source_distribution": {
        "government": 1,
        "opposition": 0,
        "expert": 0,
        "civil_society": 0,
        "corporate": 0,
        "unnamed_source": 0,
        "other": 0,
    },
    "evidence_snippets": [
        "critics said the measures would hurt small businesses",
        "opposition leaders described the announcement as tone-deaf",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_clustered_article(
    db_session,
    *,
    slug: str = "_test_enrich_a",
    url: str = "_test_url_enrich_a",
    headline: str = "Budget lauded amid criticism",
) -> tuple[Outlet, Article, Story]:
    """Create outlet + story + one article in 'clustered' state."""
    outlet = Outlet(
        name="_test outlet enrich",
        slug=slug,
        rss_url=f"https://x.example/{slug}",
        website="https://x.example",
        active=True,
    )
    db_session.add(outlet)
    db_session.flush()

    now = datetime.now(tz=timezone.utc)
    story = Story(
        title="_dbg_ enrichment story",
        first_seen_at=now,
        last_seen_at=now,
        article_count=1,
    )
    db_session.add(story)
    db_session.flush()

    article = Article(
        outlet_id=outlet.id,
        url=url,
        headline=headline,
        published_at=now,
        full_text=(
            "critics said the measures would hurt small businesses. "
            "opposition leaders described the announcement as tone-deaf. "
            "This is the body of the article. "
        ) * 5,
        processing_state="clustered",
        story_id=story.id,
    )
    db_session.add(article)
    db_session.commit()
    return outlet, article, story


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_enrich_success_persists_analysis_and_run(db_session, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model-1")
    from src.config import get_settings
    get_settings.cache_clear()

    outlet, article, story = _make_clustered_article(db_session)
    llm = FakeGroqClient(responses=[json.dumps(VALID_RESPONSE)])

    analyzed, failed = enrich_articles(db_session, llm=llm, outlet_id=outlet.id)
    assert analyzed == 1
    assert failed == 0

    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.id == article.id))
    assert a.processing_state == "analyzed"
    assert a.attempt_count == 0
    assert a.state_error is None

    # analysis_runs row
    run = db_session.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.purpose == "enrich")
        .order_by(AnalysisRun.id.desc())
    ).first()
    assert run is not None
    assert run.model_id == "test-model-1"
    assert run.prompt_version == DEFAULT_PROMPT_VERSION

    # article_analysis row — all key values persisted correctly
    aa = db_session.scalar(
        select(ArticleAnalysis).where(ArticleAnalysis.article_id == article.id)
    )
    assert aa is not None
    assert aa.analysis_run_id == run.id
    assert float(aa.framing_score) == pytest.approx(-0.5)
    assert aa.framing_label == "critical"
    assert float(aa.framing_confidence) == pytest.approx(0.8)
    assert float(aa.headline_sentiment) == pytest.approx(-0.4)
    assert float(aa.body_sentiment) == pytest.approx(-0.3)
    assert aa.key_themes == ["budget", "tax reform"]

    # quoted_sources and evidence_snippets persisted verbatim
    assert aa.quoted_sources == VALID_RESPONSE["quoted_sources"]
    assert aa.evidence_snippets == VALID_RESPONSE["evidence_snippets"]

    # entities and source_distribution round-trip through JSONB
    assert aa.entities["people"] == ["Nirmala Sitharaman"]
    assert aa.entities["organizations"] == ["Ministry of Finance"]
    assert aa.source_distribution["government"] == 1
    assert aa.source_distribution["opposition"] == 0

    # No real API call — the FakeGroqClient logs every call it saw
    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == "test-model-1"
    # The prompt got the headline substituted
    assert "Budget lauded amid criticism" in llm.calls[0]["prompt"]
    # And the outlet slug
    assert outlet.slug in llm.calls[0]["prompt"]


def test_enrich_malformed_json_leaves_article_retryable(db_session):
    outlet, article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_bad_json",
        url="_test_url_enrich_bad_json",
    )
    llm = FakeGroqClient(responses=["not valid json {{{"])

    analyzed, failed = enrich_articles(db_session, llm=llm, outlet_id=outlet.id)
    assert analyzed == 0
    assert failed == 0  # attempt 1 doesn't hit the 3-failure cap

    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.id == article.id))
    assert a.processing_state == "clustered"  # stays retryable
    assert a.attempt_count == 1
    assert a.state_error and "JSONDecodeError" in a.state_error

    # article_analysis row NOT created
    aa = db_session.scalar(
        select(ArticleAnalysis).where(ArticleAnalysis.article_id == article.id)
    )
    assert aa is None


def test_enrich_out_of_range_score_is_rejected(db_session):
    """JSON parses but framing_score is out of [-1, 1] → ValidationError."""
    bad = dict(VALID_RESPONSE, framing_score=2.5)
    outlet, article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_bad_range",
        url="_test_url_enrich_bad_range",
    )
    llm = FakeGroqClient(responses=[json.dumps(bad)])

    analyzed, failed = enrich_articles(db_session, llm=llm, outlet_id=outlet.id)
    assert analyzed == 0
    assert failed == 0

    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.id == article.id))
    assert a.processing_state == "clustered"
    assert a.attempt_count == 1
    assert a.state_error and "ValidationError" in a.state_error

    aa = db_session.scalar(
        select(ArticleAnalysis).where(ArticleAnalysis.article_id == article.id)
    )
    assert aa is None


def test_enrich_three_failures_transitions_to_failed_analyze(db_session):
    outlet, article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_3fail",
        url="_test_url_enrich_3fail",
    )

    for i in range(1, MAX_ATTEMPTS + 1):
        llm = FakeGroqClient(responses=["oops not json"])
        analyzed, failed = enrich_articles(db_session, llm=llm,
                                            outlet_id=outlet.id)
        db_session.expire_all()
        a = db_session.scalar(select(Article).where(Article.id == article.id))
        if i < MAX_ATTEMPTS:
            assert a.processing_state == "clustered", f"iter {i}"
            assert a.attempt_count == i
            assert analyzed == 0 and failed == 0
        else:
            assert a.processing_state == "failed_analyze", f"iter {i}"
            assert a.attempt_count == MAX_ATTEMPTS
            assert analyzed == 0 and failed == 1

    # A subsequent enrich_articles call must NOT touch failed_analyze rows
    llm = FakeGroqClient(responses=[])
    analyzed, failed = enrich_articles(db_session, llm=llm, outlet_id=outlet.id)
    assert analyzed == 0
    assert failed == 0
    assert llm.calls == []  # no article was even sent to the LLM


def test_enrich_no_candidates_is_no_op(db_session):
    """No clustered articles for THIS outlet → no LLM call, no analysis_runs row."""
    # Create an outlet with NO articles so the scoped query is genuinely empty.
    outlet = Outlet(
        name="_test outlet enrich empty",
        slug="_test_enrich_empty",
        rss_url="https://x.example/_test_enrich_empty",
        website="https://x.example",
        active=True,
    )
    db_session.add(outlet)
    db_session.commit()

    llm = FakeGroqClient(responses=[])

    runs_before = db_session.scalar(
        select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(1)
    )
    latest_id_before = runs_before.id if runs_before else 0

    analyzed, failed = enrich_articles(db_session, llm=llm, outlet_id=outlet.id)
    assert analyzed == 0
    assert failed == 0
    assert llm.calls == []

    # No new analysis_runs row was inserted
    runs_after = db_session.scalar(
        select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(1)
    )
    latest_id_after = runs_after.id if runs_after else 0
    assert latest_id_after == latest_id_before


def test_enrich_uses_env_llm_model(db_session, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "custom-model-xyz")
    from src.config import get_settings
    get_settings.cache_clear()

    outlet, _article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_model",
        url="_test_url_enrich_model",
    )
    llm = FakeGroqClient(responses=[json.dumps(VALID_RESPONSE)])

    enrich_articles(db_session, llm=llm, outlet_id=outlet.id)

    assert llm.calls[0]["model"] == "custom-model-xyz"

    run = db_session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.purpose == "enrich")
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    )
    assert run.model_id == "custom-model-xyz"
    assert run.prompt_version == DEFAULT_PROMPT_VERSION


def test_enrich_latest_wins_on_repeat(db_session):
    """A second enrichment for the same article overwrites the previous row."""
    outlet, article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_latest",
        url="_test_url_enrich_latest",
    )

    # First enrichment
    llm1 = FakeGroqClient(responses=[json.dumps(VALID_RESPONSE)])
    enrich_articles(db_session, llm=llm1, outlet_id=outlet.id)
    db_session.expire_all()
    aa1 = db_session.scalar(
        select(ArticleAnalysis).where(ArticleAnalysis.article_id == article.id)
    )
    first_run_id = aa1.analysis_run_id
    assert aa1.framing_label == "critical"

    # Reset back to clustered so a second enrichment picks it up
    db_session.execute(
        sqla_update(Article)
        .where(Article.id == article.id)
        .values(
            processing_state="clustered",
            state_error=None,
            attempt_count=0,
        )
    )
    db_session.commit()

    # Second enrichment with a different framing_score/label
    updated = dict(VALID_RESPONSE, framing_score=0.7, framing_label="supportive")
    llm2 = FakeGroqClient(responses=[json.dumps(updated)])
    enrich_articles(db_session, llm=llm2, outlet_id=outlet.id)
    db_session.expire_all()

    aa2 = db_session.scalar(
        select(ArticleAnalysis).where(ArticleAnalysis.article_id == article.id)
    )
    assert aa2.analysis_run_id != first_run_id
    assert float(aa2.framing_score) == pytest.approx(0.7)
    assert aa2.framing_label == "supportive"


# ---------------------------------------------------------------------------
# Fake exception classes for infrastructure-signal tests. Class NAMES
# match what production would see from the groq SDK ('RateLimitError').
# ---------------------------------------------------------------------------
class RateLimitError(Exception):
    """Mimics groq.RateLimitError — enrich classifies by class name."""

    def __init__(self, message: str = "Rate limit reached"):
        super().__init__(message)
        self.status_code = 429


class APITimeoutError(Exception):
    """Mimics groq.APITimeoutError — a real (article-agnostic) transient."""


# ---------------------------------------------------------------------------
# NEW: coverage-priority selection tests (production selection path)
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


def _make_clustered(
    db_session,
    outlet: Outlet,
    story: Story,
    *,
    url: str,
    headline: str = "_test_ clustered article",
    published_at: datetime | None = None,
) -> Article:
    a = Article(
        outlet_id=outlet.id,
        url=url,
        headline=headline,
        published_at=published_at or datetime.now(tz=timezone.utc),
        full_text="critics said the measures would hurt small businesses. "
                  "opposition leaders described the announcement as tone-deaf. "
                  "This is the body of the article. " * 5,
        processing_state="clustered",
        story_id=story.id,
    )
    db_session.add(a)
    db_session.flush()
    return a


def test_enrichment_prioritizes_multi_outlet_stories(db_session):
    """Production path (no outlet_id / no article_ids): the priority
    query MUST prefer clustered articles from multi-outlet stories over
    those from single-outlet stories, and MUST exclude single-outlet
    stories from the batch.
    """
    now = datetime.now(tz=timezone.utc)
    # 2 single-outlet stories (should be excluded from the batch)
    single_outlets = [
        _make_outlet(db_session, "_test_prio_solo_a"),
        _make_outlet(db_session, "_test_prio_solo_b"),
    ]
    single_stories = []
    single_arts = []
    for i, o in enumerate(single_outlets):
        s = Story(title=f"_dbg_ prio solo {i}", first_seen_at=now,
                  last_seen_at=now, article_count=1)
        db_session.add(s)
        db_session.flush()
        single_stories.append(s)
        single_arts.append(_make_clustered(
            db_session, o, s, url=f"_test_url_prio_solo_{i}",
        ))

    # 1 multi-outlet story (2 outlets, 2 clustered articles). Priority.
    multi_outlets = [
        _make_outlet(db_session, "_test_prio_multi_a"),
        _make_outlet(db_session, "_test_prio_multi_b"),
    ]
    multi_story = Story(title="_dbg_ prio multi", first_seen_at=now,
                        last_seen_at=now, article_count=2)
    db_session.add(multi_story)
    db_session.flush()
    multi_arts = [
        _make_clustered(db_session, multi_outlets[0], multi_story,
                        url="_test_url_prio_multi_a"),
        _make_clustered(db_session, multi_outlets[1], multi_story,
                        url="_test_url_prio_multi_b"),
    ]
    db_session.commit()

    llm = FakeGroqClient(responses=[json.dumps(VALID_RESPONSE)] * 2)

    # Ask for up to 4; production PRIORITY path scoped to this test's
    # stories so the shared dev-test DB's real multi-outlet coverage
    # cannot rank above our fixtures. Should pick BOTH multi-outlet
    # articles; MUST NOT pick either single-outlet article.
    scoped_story_ids = [s.id for s in single_stories] + [multi_story.id]
    result = enrich_articles(
        db_session, llm=llm, batch_limit=4, story_ids=scoped_story_ids,
    )
    assert result.analyzed == 2, "should analyze exactly the 2 multi-outlet articles"
    assert result.rate_limited is False

    db_session.expire_all()
    # Multi-outlet articles moved to analyzed
    for a in multi_arts:
        row = db_session.scalar(select(Article).where(Article.id == a.id))
        assert row.processing_state == "analyzed", f"aid={a.id}"
    # Single-outlet articles UNTOUCHED — still clustered, no attempts
    for a in single_arts:
        row = db_session.scalar(select(Article).where(Article.id == a.id))
        assert row.processing_state == "clustered", f"aid={a.id}"
        assert row.attempt_count == 0


def test_enrichment_respects_budget_via_batch_limit(db_session):
    """batch_limit caps how many articles the priority query returns."""
    now = datetime.now(tz=timezone.utc)
    o1 = _make_outlet(db_session, "_test_budget_o1")
    o2 = _make_outlet(db_session, "_test_budget_o2")

    stories, arts = [], []
    # 3 multi-outlet stories (each 2 outlets, 2 articles) → 6 eligible articles
    for i in range(3):
        s = Story(title=f"_dbg_ budget story {i}", first_seen_at=now,
                  last_seen_at=now, article_count=2)
        db_session.add(s)
        db_session.flush()
        stories.append(s)
        arts.append(_make_clustered(db_session, o1, s,
                                    url=f"_test_url_budget_a_{i}"))
        arts.append(_make_clustered(db_session, o2, s,
                                    url=f"_test_url_budget_b_{i}"))
    db_session.commit()

    llm = FakeGroqClient(responses=[json.dumps(VALID_RESPONSE)] * 3)
    # Budget = 3 → exactly 3 analyzed, 3 remain clustered.
    # story_ids scopes the priority path to this test's stories only.
    scoped_story_ids = [st.id for st in stories]
    result = enrich_articles(
        db_session, llm=llm, batch_limit=3, story_ids=scoped_story_ids,
    )
    assert result.analyzed == 3
    assert result.rate_limited is False
    assert len(llm.calls) == 3

    db_session.expire_all()
    analyzed = [a for a in arts
                if db_session.scalar(select(Article).where(Article.id == a.id))
                              .processing_state == "analyzed"]
    still_clustered = [a for a in arts
                       if db_session.scalar(select(Article).where(Article.id == a.id))
                                     .processing_state == "clustered"]
    assert len(analyzed) == 3
    assert len(still_clustered) == 3


def test_ratelimit_error_does_not_bump_attempt_count(db_session):
    """A Groq 429 (RateLimitError) leaves the article's state and
    attempt_count UNCHANGED, records state_error, and returns
    rate_limited=True.
    """
    outlet, article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_429",
        url="_test_url_enrich_429",
    )
    llm = FakeGroqClient(raise_for=[RateLimitError("TPM budget exceeded")])

    result = enrich_articles(db_session, llm=llm, outlet_id=outlet.id)
    assert result.analyzed == 0
    assert result.failed_permanent == 0
    assert result.rate_limited is True

    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.id == article.id))
    assert a.processing_state == "clustered", "429 must not change state"
    assert a.attempt_count == 0, "429 must not consume attempt budget"
    assert a.state_error and "RateLimitError" in a.state_error


def test_ratelimit_can_be_retried_indefinitely(db_session):
    """Five consecutive 429s do NOT promote the article to
    failed_analyze (which the pre-fix code would do after 3 attempts).
    """
    outlet, article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_429_many",
        url="_test_url_enrich_429_many",
    )
    for _ in range(5):
        llm = FakeGroqClient(raise_for=[RateLimitError()])
        result = enrich_articles(db_session, llm=llm, outlet_id=outlet.id)
        assert result.rate_limited is True

    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.id == article.id))
    assert a.processing_state == "clustered"
    assert a.attempt_count == 0


def test_pydantic_validation_error_still_bumps_attempt_count(db_session):
    """Regression: article-content failures (Pydantic) MUST still bump
    attempt_count. Only 429 gets the free pass.
    """
    bad = dict(VALID_RESPONSE, framing_score=42.0)  # out of range
    outlet, article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_val",
        url="_test_url_enrich_val",
    )
    llm = FakeGroqClient(responses=[json.dumps(bad)])
    result = enrich_articles(db_session, llm=llm, outlet_id=outlet.id)
    assert result.rate_limited is False
    assert result.failed_permanent == 0
    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.id == article.id))
    assert a.attempt_count == 1, "content failures MUST consume attempt budget"


def test_enrichment_never_reanalyzes_analyzed_articles(db_session):
    """Regression: articles already in state='analyzed' MUST NOT be
    picked up by enrich_articles, whether we use the filter path or the
    priority path.
    """
    outlet, article, _ = _make_clustered_article(
        db_session, slug="_test_enrich_no_reanalyze",
        url="_test_url_enrich_no_reanalyze",
    )
    llm1 = FakeGroqClient(responses=[json.dumps(VALID_RESPONSE)])
    enrich_articles(db_session, llm=llm1, outlet_id=outlet.id)
    db_session.expire_all()
    a = db_session.scalar(select(Article).where(Article.id == article.id))
    assert a.processing_state == "analyzed"

    # Filter path: no candidates for this outlet
    llm2 = FakeGroqClient(responses=[])
    r_filter = enrich_articles(db_session, llm=llm2, outlet_id=outlet.id)
    assert r_filter.analyzed == 0
    assert llm2.calls == []

    # Priority path scoped to this article's story: the already-analyzed
    # article MUST NOT reappear as a candidate. We prove that by
    # asserting the priority query returns [] for this story (its only
    # article is 'analyzed', not 'clustered'), and the row stays
    # 'analyzed' with attempt_count unchanged.
    llm3 = FakeGroqClient(responses=[])
    enrich_articles(
        db_session, llm=llm3, batch_limit=1,
        story_ids=[article.story_id] if article.story_id else [],
    )
    db_session.expire_all()
    a2 = db_session.scalar(select(Article).where(Article.id == article.id))
    assert a2.processing_state == "analyzed"
    assert a2.attempt_count == 0
    assert llm3.calls == [], "priority path must not re-enrich an analyzed article"
