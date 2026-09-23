"""Tests for the story-comparison stage.

Uses a local ``FakeGroqClient`` injected via the ``LLMClient`` Protocol
so tests never make real Groq calls. Covers success, skip-cases,
malformed JSON, invalid coverage-matrix ranges, latest-wins, no-op
when there are no candidates, env-driven model/prompt-version, and
multi-story batch behaviour.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.db.models import (
    AnalysisRun,
    Article,
    ArticleAnalysis,
    Outlet,
    Story,
    StoryComparison,
)
from src.ingestion.compare import (
    DEFAULT_PROMPT_VERSION,
    MIN_ARTICLES,
    MIN_OUTLETS,
    compare_stories,
)


# ---------------------------------------------------------------------------
# Local fake LLM — kept independent of test_enrich.py to avoid a
# test-to-test import dependency.
# ---------------------------------------------------------------------------
class FakeGroqClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls: list[dict] = []

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> str:
        self.calls.append(
            {"model": model, "prompt": prompt, "timeout_s": timeout_s}
        )
        if not self.responses:
            raise AssertionError("FakeGroqClient exhausted responses")
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# Fixture builder — creates outlets + story + analyzed articles +
# article_analysis rows in a single db_session.commit().
# ---------------------------------------------------------------------------
def _make_analyzed_story(
    db_session,
    *,
    n_articles: int,
    n_outlets: int,
    slug_prefix: str,
    url_prefix: str,
    story_title: str = "_dbg_ compare story",
    framing_scores: list[float] | None = None,
) -> tuple[list[Outlet], Story, list[Article]]:
    now = datetime.now(tz=timezone.utc)

    outlets: list[Outlet] = []
    for i in range(n_outlets):
        o = Outlet(
            name=f"_test outlet {slug_prefix} {i}",
            slug=f"{slug_prefix}_o{i}",
            rss_url=f"https://x.example/{slug_prefix}_{i}",
            website="https://x.example",
            active=True,
        )
        db_session.add(o)
        outlets.append(o)
    db_session.flush()

    story = Story(
        title=story_title,
        first_seen_at=now,
        last_seen_at=now,
        article_count=n_articles,
    )
    db_session.add(story)
    db_session.flush()

    # An enrichment-purpose AnalysisRun to attach the ArticleAnalysis rows to
    enrich_run = AnalysisRun(
        ran_at=now,
        model_id="test-enrich-model",
        prompt_version="enrich_v1",
        purpose="enrich",
    )
    db_session.add(enrich_run)
    db_session.flush()

    if framing_scores is None:
        # Spread evenly from -0.5 to +0.5 by default
        if n_articles == 1:
            framing_scores = [0.0]
        else:
            step = 1.0 / (n_articles - 1)
            framing_scores = [-0.5 + i * step for i in range(n_articles)]

    articles: list[Article] = []
    for i in range(n_articles):
        outlet = outlets[i % len(outlets)]
        article = Article(
            outlet_id=outlet.id,
            url=f"{url_prefix}_{i:02d}",
            headline=f"_test article {i} on this story",
            published_at=now,
            full_text=f"body of article {i}. " * 10,
            processing_state="analyzed",
            story_id=story.id,
        )
        db_session.add(article)
        db_session.flush()
        articles.append(article)

        aa = ArticleAnalysis(
            article_id=article.id,
            analysis_run_id=enrich_run.id,
            framing_score=Decimal(str(round(framing_scores[i], 2))),
            framing_label=(
                "critical"    if framing_scores[i] <= -0.33
                else "supportive" if framing_scores[i] >=  0.33
                else "neutral"
            ),
            framing_confidence=Decimal("0.75"),
            headline_sentiment=Decimal("0.0"),
            body_sentiment=Decimal("0.0"),
            key_themes=["budget", f"theme_{i}"],
            entities={
                "people":        [f"Person {i}"],
                "organizations": [],
                "locations":     [],
                "other":         [],
            },
            quoted_sources=[{
                "speaker":     f"Speaker {i}",
                "affiliation": None,
                "quote":       f"Quote number {i} verbatim.",
                "stance":      "neutral",
            }],
            source_distribution={
                "government": 0, "opposition": 0, "expert": 0,
                "civil_society": 0, "corporate": 0,
                "unnamed_source": 0, "other": 1,
            },
            evidence_snippets=[f"evidence snippet number {i}"],
        )
        db_session.add(aa)

    db_session.commit()
    return outlets, story, articles


def _valid_response(outlets: list[Outlet], theme_list: list[str]) -> dict:
    """Build a schema-valid ComparisonResponse for a given (outlets, themes)."""
    coverage_matrix = {
        o.slug: {t: (1.0 if i == 0 else 0.3) for i, t in enumerate(theme_list)}
        for o in outlets
    }
    not_present_here: dict[str, list[str]] = {o.slug: [] for o in outlets}
    if len(outlets) >= 2:
        not_present_here[outlets[0].slug] = [
            "a fact stated only by outlet 1"
        ]
    return {
        "differences": (
            f"- {outlets[0].slug} emphasizes the budget theme heavily.\n"
            f"- {outlets[-1].slug} focuses more on secondary themes."
        ),
        "coverage_matrix": coverage_matrix,
        "not_present_here": not_present_here,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_compare_success_persists_story_comparison(db_session, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-compare-model")
    from src.config import get_settings
    get_settings.cache_clear()

    outlets, story, articles = _make_analyzed_story(
        db_session,
        n_articles=3, n_outlets=3,
        slug_prefix="_test_cmp_s1",
        url_prefix="_test_url_cmp_s1",
        framing_scores=[-0.6, 0.0, 0.6],
    )
    # Union of key_themes in first-seen order:
    #   article 0 → ["budget", "theme_0"]
    #   article 1 → ["budget", "theme_1"]  ("budget" already seen)
    #   article 2 → ["budget", "theme_2"]
    theme_list = ["budget", "theme_0", "theme_1", "theme_2"]
    resp = _valid_response(outlets, theme_list)
    llm = FakeGroqClient(responses=[json.dumps(resp)])

    compared, failed = compare_stories(
        db_session, llm=llm, story_ids=[story.id],
    )
    assert compared == 1
    assert failed == 0

    db_session.expire_all()

    # story_comparisons row present with expected fields
    sc = db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story.id)
    )
    assert sc is not None
    assert sc.differences.startswith("-")
    assert isinstance(sc.coverage_matrix, dict)
    for o in outlets:
        assert o.slug in sc.coverage_matrix
        for theme in theme_list:
            assert theme in sc.coverage_matrix[o.slug]
    assert isinstance(sc.not_present_here, dict)

    # framing_spread deterministic — population std-dev of [-0.6, 0.0, 0.6]
    expected = statistics.pstdev([-0.6, 0.0, 0.6])
    assert float(sc.framing_spread) == pytest.approx(round(expected, 2), abs=0.01)

    # analysis_runs row: purpose='compare', correct model + prompt version
    run = db_session.scalar(
        select(AnalysisRun).where(AnalysisRun.id == sc.analysis_run_id)
    )
    assert run is not None
    assert run.purpose == "compare"
    assert run.model_id == "test-compare-model"
    assert run.prompt_version == DEFAULT_PROMPT_VERSION

    # All participating articles advanced to 'complete'
    post_states = [
        a.processing_state for a in db_session.scalars(
            select(Article).where(Article.story_id == story.id)
        ).all()
    ]
    assert post_states and all(s == "complete" for s in post_states)

    # LLM called exactly once, with the correct model + prompt contents
    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == "test-compare-model"
    prompt = llm.calls[0]["prompt"]
    assert story.title in prompt
    for o in outlets:
        assert o.slug in prompt
    for t in theme_list:
        assert t in prompt


def test_compare_skips_story_with_single_article(db_session):
    outlets, story, articles = _make_analyzed_story(
        db_session,
        n_articles=1, n_outlets=1,
        slug_prefix="_test_cmp_one_art",
        url_prefix="_test_url_cmp_one_art",
    )
    llm = FakeGroqClient(responses=[])

    compared, failed = compare_stories(
        db_session, llm=llm, story_ids=[story.id],
    )
    assert compared == 0
    assert failed == 0
    assert llm.calls == []

    db_session.expire_all()
    assert db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story.id)
    ) is None
    a = db_session.scalar(select(Article).where(Article.id == articles[0].id))
    assert a.processing_state == "analyzed"


def test_compare_skips_story_with_single_outlet(db_session):
    outlets, story, articles = _make_analyzed_story(
        db_session,
        n_articles=3, n_outlets=1,   # 3 articles, all from 1 outlet
        slug_prefix="_test_cmp_one_outlet",
        url_prefix="_test_url_cmp_one_outlet",
    )
    assert len(outlets) == 1
    llm = FakeGroqClient(responses=[])

    compared, failed = compare_stories(
        db_session, llm=llm, story_ids=[story.id],
    )
    assert compared == 0
    assert failed == 0
    assert llm.calls == []

    db_session.expire_all()
    assert db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story.id)
    ) is None
    for a in db_session.scalars(
        select(Article).where(Article.story_id == story.id)
    ).all():
        assert a.processing_state == "analyzed"


def test_compare_malformed_json_leaves_articles_at_analyzed(db_session):
    outlets, story, articles = _make_analyzed_story(
        db_session,
        n_articles=2, n_outlets=2,
        slug_prefix="_test_cmp_bad_json",
        url_prefix="_test_url_cmp_bad_json",
    )
    llm = FakeGroqClient(responses=["not valid json {{{"])

    compared, failed = compare_stories(
        db_session, llm=llm, story_ids=[story.id],
    )
    assert compared == 0
    assert failed == 0
    assert len(llm.calls) == 1   # LLM WAS called, response was garbage

    db_session.expire_all()
    assert db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story.id)
    ) is None
    for a in db_session.scalars(
        select(Article).where(Article.story_id == story.id)
    ).all():
        assert a.processing_state == "analyzed"


def test_compare_out_of_range_coverage_value_rejected(db_session):
    outlets, story, articles = _make_analyzed_story(
        db_session,
        n_articles=2, n_outlets=2,
        slug_prefix="_test_cmp_bad_cov",
        url_prefix="_test_url_cmp_bad_cov",
    )
    theme_list = ["budget", "theme_0", "theme_1"]
    resp = _valid_response(outlets, theme_list)
    # break one coverage value (must be in [0, 1])
    resp["coverage_matrix"][outlets[0].slug][theme_list[0]] = 1.5
    llm = FakeGroqClient(responses=[json.dumps(resp)])

    compared, failed = compare_stories(
        db_session, llm=llm, story_ids=[story.id],
    )
    assert compared == 0
    assert failed == 0

    db_session.expire_all()
    assert db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story.id)
    ) is None
    for a in db_session.scalars(
        select(Article).where(Article.story_id == story.id)
    ).all():
        assert a.processing_state == "analyzed"


def test_compare_latest_wins_on_repeat(db_session):
    outlets, story, articles = _make_analyzed_story(
        db_session,
        n_articles=2, n_outlets=2,
        slug_prefix="_test_cmp_latest",
        url_prefix="_test_url_cmp_latest",
    )
    theme_list = ["budget", "theme_0", "theme_1"]

    # First comparison — succeeds and moves articles to 'complete'
    llm1 = FakeGroqClient(
        responses=[json.dumps(_valid_response(outlets, theme_list))]
    )
    compare_stories(db_session, llm=llm1, story_ids=[story.id])
    db_session.expire_all()
    sc1 = db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story.id)
    )
    first_run_id = sc1.analysis_run_id
    first_differences = sc1.differences

    # Reset articles back to 'analyzed' so a re-compare will pick up the story
    for a in db_session.scalars(
        select(Article).where(Article.story_id == story.id)
    ).all():
        a.processing_state = "analyzed"
    db_session.commit()

    # Second comparison with different `differences` text
    updated = _valid_response(outlets, theme_list)
    updated["differences"] = (
        "- Completely different comparison text for the second pass."
    )
    llm2 = FakeGroqClient(responses=[json.dumps(updated)])
    compare_stories(db_session, llm=llm2, story_ids=[story.id])
    db_session.expire_all()

    sc2 = db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story.id)
    )
    assert sc2.analysis_run_id != first_run_id
    assert sc2.differences != first_differences
    assert sc2.differences.startswith("- Completely different")


def test_compare_no_candidate_stories_is_no_op(db_session):
    """A story with only 'clustered' articles is not a candidate."""
    now = datetime.now(tz=timezone.utc)
    outlet = Outlet(
        name="_test outlet no_cand",
        slug="_test_cmp_no_cand_o0",
        rss_url="https://x.example/no_cand",
        website="https://x.example",
        active=True,
    )
    db_session.add(outlet)
    db_session.flush()
    story = Story(
        title="_dbg_ compare no-cand story",
        first_seen_at=now, last_seen_at=now, article_count=0,
    )
    db_session.add(story)
    db_session.flush()
    # 1 article, and it's only 'clustered' — not analyzed → not a candidate
    db_session.add(Article(
        outlet_id=outlet.id,
        url="_test_url_cmp_no_cand",
        headline="_test article no_cand",
        published_at=now,
        processing_state="clustered",
        story_id=story.id,
    ))
    db_session.commit()

    llm = FakeGroqClient(responses=[])
    runs_before = db_session.scalar(
        select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(1)
    )
    latest_before = runs_before.id if runs_before else 0

    compared, failed = compare_stories(
        db_session, llm=llm, story_ids=[story.id],
    )
    assert compared == 0
    assert failed == 0
    assert llm.calls == []

    # No new compare-purpose AnalysisRun row was created
    latest_compare = db_session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.purpose == "compare")
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    )
    if latest_compare is not None:
        assert latest_compare.id <= latest_before


def test_compare_uses_env_llm_model_and_prompt_version(db_session, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "custom-compare-model")
    from src.config import get_settings
    get_settings.cache_clear()

    outlets, story, _ = _make_analyzed_story(
        db_session,
        n_articles=2, n_outlets=2,
        slug_prefix="_test_cmp_env",
        url_prefix="_test_url_cmp_env",
    )
    theme_list = ["budget", "theme_0", "theme_1"]
    llm = FakeGroqClient(
        responses=[json.dumps(_valid_response(outlets, theme_list))]
    )

    compare_stories(db_session, llm=llm, story_ids=[story.id])

    assert llm.calls[0]["model"] == "custom-compare-model"

    run = db_session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.purpose == "compare")
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    )
    assert run.model_id == "custom-compare-model"
    assert run.prompt_version == DEFAULT_PROMPT_VERSION


def test_compare_batch_shares_one_analysis_run(db_session):
    """Two qualifying stories in one call → one analysis_runs row shared."""
    outlets1, story1, _ = _make_analyzed_story(
        db_session,
        n_articles=2, n_outlets=2,
        slug_prefix="_test_cmp_bat_a",
        url_prefix="_test_url_cmp_bat_a",
        story_title="_dbg_ compare story A",
    )
    outlets2, story2, _ = _make_analyzed_story(
        db_session,
        n_articles=2, n_outlets=2,
        slug_prefix="_test_cmp_bat_b",
        url_prefix="_test_url_cmp_bat_b",
        story_title="_dbg_ compare story B",
    )
    theme_list = ["budget", "theme_0", "theme_1"]
    llm = FakeGroqClient(responses=[
        json.dumps(_valid_response(outlets1, theme_list)),
        json.dumps(_valid_response(outlets2, theme_list)),
    ])

    compared, failed = compare_stories(
        db_session, llm=llm, story_ids=[story1.id, story2.id],
    )
    assert compared == 2
    assert failed == 0
    assert len(llm.calls) == 2

    db_session.expire_all()
    sc1 = db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story1.id)
    )
    sc2 = db_session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story2.id)
    )
    assert sc1 is not None and sc2 is not None
    # Single AnalysisRun shared across the batch
    assert sc1.analysis_run_id == sc2.analysis_run_id

    # Both stories' articles advanced to 'complete'
    for sid in (story1.id, story2.id):
        for a in db_session.scalars(
            select(Article).where(Article.story_id == sid)
        ).all():
            assert a.processing_state == "complete"


# Constants smoke-test — protects against accidental threshold change
def test_compare_thresholds_are_2_and_2():
    assert MIN_ARTICLES == 2
    assert MIN_OUTLETS == 2
