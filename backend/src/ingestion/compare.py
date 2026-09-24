"""Per-story LLM comparison summary.

Reads stories whose articles are in state ``analyzed`` or ``complete``
and, when there are at least ``MIN_ARTICLES`` articles from at least
``MIN_OUTLETS`` distinct outlets, calls the LLM to produce a comparison,
upserts one ``story_comparisons`` row (latest-wins on ``story_id``),
and advances any still-``analyzed`` articles to ``complete``.

Design notes (arch §9 / §10 step 9 / §17 / Appendix C):
  - ``framing_spread`` is computed DETERMINISTICALLY as the population
    standard deviation of the story's articles' ``framing_score``
    values. The LLM does not compute it. Matches the schema comment
    "std-dev of framing across outlets".
  - ``coverage_matrix`` uses a FIXED theme list — the union of
    ``article_analysis.key_themes`` across the story's articles,
    first-seen order. The LLM is instructed (in the prompt) to output
    exactly those themes under every outlet.
  - ``not_present_here`` is LLM-generated and grounded by prompt
    instruction on the enrichment payloads that were passed in.
  - No per-story ``attempt_count`` column exists (schema is locked);
    a comparison failure simply doesn't write the row and leaves the
    articles in ``analyzed``. The next pipeline cycle retries them.
    This mirrors arch §10: "On failure at any step, the article stays
    in its current state; the next run picks it up."
  - The LLM client (``LLMClient`` Protocol and ``GroqClient`` impl)
    is imported from ``enrich.py`` — one implementation for the whole
    pipeline.

Incremental / late-arriving article behaviour (added 2026-09-24):
  - Candidate selection considers articles in state IN
    ('analyzed', 'complete') so that a previously-compared story
    (articles now ``complete``) can be re-compared once a new outlet
    joins and reaches ``analyzed`` state.
  - The "fresh coverage" gate requires the story's latest
    state_updated_at for an ``analyzed`` article to post-date the
    existing ``story_comparisons.generated_at``. Stories that are fully
    ``complete`` with no new arrivals are not re-compared each cycle.
  - Existing ``article_analysis`` rows are reused as-is. No article is
    re-enriched merely because a story gained a new sibling.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.config import get_settings
from src.db.models import (
    AnalysisRun,
    Article,
    ArticleAnalysis,
    Outlet,
    Story,
    StoryComparison,
)
from src.ingestion.compare_schema import ComparisonResponse
# Reuse the exact LLM abstractions used by enrichment.
from src.ingestion.enrich import GroqClient, LLMClient  # noqa: F401 (re-export)

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

DEFAULT_PROMPT_VERSION = "compare_v1"
DEFAULT_TIMEOUT_S = 30.0
# Compare calls carry more data than enrich (many articles per prompt).
# Keep the batch small so a bad publisher / rate limit doesn't cascade.
DEFAULT_BATCH_LIMIT = 10

MIN_ARTICLES = 2   # need at least two articles to compare
MIN_OUTLETS  = 2   # …from at least two different outlets


def _load_prompt(version: str) -> str:
    path = PROMPTS_DIR / f"{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if text.strip().startswith("PLACEHOLDER"):
        raise ValueError(f"prompt {version!r} is still a placeholder")
    return text


def _render_prompt(template: str, *, story_title: str,
                   theme_list: list[str], articles_json: str) -> str:
    """Fill the {story_title}/{theme_list}/{articles_json} placeholders."""
    themes_str = "\n".join(f"- {t}" for t in theme_list) if theme_list else "(none)"
    return (
        template
        .replace("{story_title}", story_title or "")
        .replace("{theme_list}", themes_str)
        .replace("{articles_json}", articles_json)
    )


_CANDIDATES_SQL = text("""
    WITH story_stats AS (
      SELECT a.story_id,
             COUNT(*)                    AS n_articles,
             COUNT(DISTINCT a.outlet_id) AS n_outlets,
             -- Fresh coverage marker: the latest state_updated_at
             -- across articles CURRENTLY in state='analyzed' — i.e.
             -- articles that have not yet been included in a comparison.
             -- NULL when every article is already 'complete'.
             MAX(a.state_updated_at) FILTER (
               WHERE a.processing_state = 'analyzed'
             )                           AS latest_analyzed_at
        FROM articles a
       WHERE a.story_id IS NOT NULL
         AND a.processing_state IN ('analyzed', 'complete')
       GROUP BY a.story_id
      HAVING COUNT(*) >= :min_articles
         AND COUNT(DISTINCT a.outlet_id) >= :min_outlets
    )
    SELECT s.story_id
      FROM story_stats s
      LEFT JOIN story_comparisons sc ON sc.story_id = s.story_id
     WHERE
        -- Not yet compared (any state combo above the thresholds
        -- qualifies for the first comparison), OR
        sc.story_id IS NULL
        OR
        -- Fresh 'analyzed' coverage arrived after the last comparison.
        (s.latest_analyzed_at IS NOT NULL
         AND s.latest_analyzed_at > sc.generated_at)
     ORDER BY s.story_id
     LIMIT :lim
""")


def _story_candidates(
    session: Session, *,
    batch_limit: int,
    story_ids: list[int] | None,
) -> list[int]:
    """Return story_ids qualified for (re)comparison.

    A story qualifies when it has >= MIN_ARTICLES articles from >=
    MIN_OUTLETS distinct outlets in state ('analyzed', 'complete') AND
    either has no prior comparison OR has a currently-'analyzed'
    article that post-dates the existing comparison ("fresh coverage"
    gate — see module docstring).

    ``story_ids`` scopes to a specific list (used by tests and by a
    hypothetical manual retry path). If explicit ``story_ids`` is given
    we apply the fresh-coverage gate anyway — you never want a caller
    to trigger a no-op re-compare that spends LLM budget on a story
    whose comparison is already current.
    """
    if story_ids is not None and not story_ids:
        return []

    if story_ids is None:
        rows = session.execute(
            _CANDIDATES_SQL,
            {
                "min_articles": MIN_ARTICLES,
                "min_outlets": MIN_OUTLETS,
                "lim": batch_limit,
            },
        ).all()
    else:
        # Same shape as the CTE but scoped to the caller-supplied ids.
        ids_sql = ",".join(str(int(i)) for i in story_ids)
        scoped_sql = text(f"""
            WITH story_stats AS (
              SELECT a.story_id,
                     COUNT(*)                    AS n_articles,
                     COUNT(DISTINCT a.outlet_id) AS n_outlets,
                     MAX(a.state_updated_at) FILTER (
                       WHERE a.processing_state = 'analyzed'
                     )                           AS latest_analyzed_at
                FROM articles a
               WHERE a.story_id IN ({ids_sql})
                 AND a.processing_state IN ('analyzed', 'complete')
               GROUP BY a.story_id
              HAVING COUNT(*) >= :min_articles
                 AND COUNT(DISTINCT a.outlet_id) >= :min_outlets
            )
            SELECT s.story_id
              FROM story_stats s
              LEFT JOIN story_comparisons sc ON sc.story_id = s.story_id
             WHERE sc.story_id IS NULL
                OR (s.latest_analyzed_at IS NOT NULL
                    AND s.latest_analyzed_at > sc.generated_at)
             ORDER BY s.story_id
             LIMIT :lim
        """)
        rows = session.execute(
            scoped_sql,
            {
                "min_articles": MIN_ARTICLES,
                "min_outlets": MIN_OUTLETS,
                "lim": batch_limit,
            },
        ).all()

    return [int(r.story_id) for r in rows]


def _load_story_context(
    session: Session, story_id: int,
) -> tuple[Story | None, list[dict], list[float]]:
    """Return (story, per-article records ordered by article.id, framing_scores)."""
    story = session.scalar(select(Story).where(Story.id == story_id))
    if story is None:
        return None, [], []

    # Load ALL articles for this story that have a persisted analysis
    # AND are in a state that reflects successful analysis — i.e.
    # 'analyzed' (fresh) or 'complete' (included in a previous
    # comparison). Reuses existing article_analysis rows verbatim; no
    # article is re-enriched merely because a story grew.
    rows = session.execute(
        select(Article, Outlet.slug, ArticleAnalysis)
        .join(Outlet, Outlet.id == Article.outlet_id)
        .join(ArticleAnalysis, ArticleAnalysis.article_id == Article.id)
        .where(Article.story_id == story_id)
        .where(Article.processing_state.in_(("analyzed", "complete")))
        .order_by(Article.id)
    ).all()

    records: list[dict] = []
    framing_scores: list[float] = []
    for article, slug, aa in rows:
        fs = float(aa.framing_score) if aa.framing_score is not None else None
        if fs is not None:
            framing_scores.append(fs)
        records.append({
            "outlet_slug":        slug,
            "article_id":         article.id,
            "headline":           article.headline,
            "framing_score":      fs,
            "framing_label":      aa.framing_label,
            "framing_confidence": (
                float(aa.framing_confidence)
                if aa.framing_confidence is not None else None
            ),
            "key_themes":         list(aa.key_themes or []),
            "entities":           aa.entities or {},
            "quoted_sources":     aa.quoted_sources or [],
            "evidence_snippets":  aa.evidence_snippets or [],
        })
    return story, records, framing_scores


def _theme_union(records: list[dict]) -> list[str]:
    """Union of key_themes across all articles, deterministic first-seen order."""
    seen: dict[str, None] = {}
    for r in records:
        for t in r.get("key_themes") or []:
            if isinstance(t, str):
                s = t.strip()
                if s and s not in seen:
                    seen[s] = None
    return list(seen.keys())


def _compute_framing_spread(framing_scores: list[float]) -> float:
    """Population std-dev clamped to the schema range [0, 2] (Numeric(3,2))."""
    if len(framing_scores) < 2:
        return 0.0
    spread = float(statistics.pstdev(framing_scores))
    return max(0.0, min(2.0, spread))


def compare_stories(
    session: Session,
    *,
    llm: LLMClient,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    model_id: str | None = None,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    story_ids: list[int] | None = None,
) -> tuple[int, int]:
    """Compare up to ``batch_limit`` qualifying stories.

    Returns ``(compared, failed_permanent)``. ``failed_permanent`` is
    always 0: stories have no attempt_count column and no 3-strike cap,
    so failed comparisons just stay retryable (their articles remain in
    ``analyzed``). The tuple shape is kept for parity with
    ``extract_articles`` / ``enrich_articles``.

    If ``story_ids`` is given, only those stories are considered — used
    by tests to isolate from real production data.
    """
    model_id = model_id or get_settings().llm_model
    template = _load_prompt(prompt_version)

    candidate_ids = _story_candidates(
        session, batch_limit=batch_limit, story_ids=story_ids,
    )
    if not candidate_ids:
        return 0, 0

    log.info("compare: %d candidate stories", len(candidate_ids))

    # Phase 1 — LLM calls + validation. NO database writes. If everything
    # in this phase fails, we return without ever inserting an
    # analysis_runs row.
    successful: list[tuple[int, ComparisonResponse, float]] = []

    for sid in candidate_ids:
        story, records, framing_scores = _load_story_context(session, sid)
        if story is None or len(records) < MIN_ARTICLES:
            # Defensive; candidate query should already exclude this.
            continue

        theme_list = _theme_union(records)
        articles_json = json.dumps(records, ensure_ascii=False)
        prompt = _render_prompt(
            template,
            story_title=story.title or "",
            theme_list=theme_list,
            articles_json=articles_json,
        )

        try:
            raw = llm.complete(model=model_id, prompt=prompt,
                                timeout_s=timeout_s)
            data = json.loads(raw)
            validated = ComparisonResponse.model_validate(data)
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:400]}"
            log.warning("compare: story_id=%s failed: %s", sid, err)
            continue

        framing_spread = _compute_framing_spread(framing_scores)
        successful.append((sid, validated, framing_spread))

    if not successful:
        # Nothing to persist. Roll back any pending SELECT snapshot so the
        # session is clean for the caller.
        session.rollback()
        log.info("compare: 0/%d stories compared this call", len(candidate_ids))
        return 0, 0

    # Phase 2 — one AnalysisRun row, then per-story upserts + article
    # state advances, all in one transaction. Either the whole batch
    # commits or nothing does.
    run = AnalysisRun(
        ran_at=datetime.now(tz=timezone.utc),
        model_id=model_id,
        prompt_version=prompt_version,
        purpose="compare",
    )
    session.add(run)
    session.flush()   # populate run.id
    run_id = run.id

    for sid, validated, framing_spread in successful:
        ins = pg_insert(StoryComparison).values(
            story_id=sid,
            analysis_run_id=run_id,
            differences=validated.differences,
            framing_spread=round(framing_spread, 2),
            coverage_matrix=validated.coverage_matrix,
            not_present_here=validated.not_present_here,
            generated_at=datetime.now(tz=timezone.utc),
        )
        ins = ins.on_conflict_do_update(
            index_elements=["story_id"],
            set_={
                "analysis_run_id":  ins.excluded.analysis_run_id,
                "differences":      ins.excluded.differences,
                "framing_spread":   ins.excluded.framing_spread,
                "coverage_matrix":  ins.excluded.coverage_matrix,
                "not_present_here": ins.excluded.not_present_here,
                "generated_at":     ins.excluded.generated_at,
            },
        )
        session.execute(ins)
        session.execute(
            update(Article)
            .where(Article.story_id == sid)
            .where(Article.processing_state == "analyzed")
            .values(
                processing_state="complete",
                state_updated_at=datetime.now(tz=timezone.utc),
                state_error=None,
            )
        )

    session.commit()
    log.info("compare: compared=%d run_id=%s (batch of %d candidates)",
             len(successful), run_id, len(candidate_ids))
    return len(successful), 0
