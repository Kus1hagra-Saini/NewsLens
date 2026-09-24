"""Per-article LLM enrichment (framing, sentiment, entities, themes, quotes).

Reads articles in state ``clustered`` and advances them to ``analyzed``,
or to ``failed_analyze`` after the documented 3-failure retry cap.

Design notes (arch §10, §17):
  - One ``analysis_runs`` row is inserted per invocation batch — it
    records the model + prompt version used for the LLM calls in that
    batch, so any article_analysis row can be traced back to the exact
    prompt bytes.
  - Prompt files live under ``src/prompts/`` and are versioned by
    filename (``enrich_v1.txt``, ``enrich_v2.txt``, ...). Never edit an
    existing version in place; add a new file (arch §17).
  - Retry semantics reuse the ``attempt_count`` / ``state_error``
    convention from ``fetch.py`` (the same 3-strike rule from
    Appendix A). No new state, no new columns.
  - The Groq client is instantiated lazily, so the module imports
    cleanly in environments without the groq SDK or without an API key
    (which matters for unit tests, which inject a fake ``LLMClient``).

Priority (coverage priority):
  Production selection prefers articles that will produce comparative
  value — i.e. clustered articles whose story already carries at least
  two distinct outlets. Single-outlet stories stay stored and pending;
  they become eligible the moment a second outlet joins.
  The ordering is deterministic and DB-only — no LLM in the loop, no
  hidden editorial ranking:
      P1: multi-outlet story that already has a comparison
      P2: multi-outlet story that does not yet have a comparison
  Single-outlet stories are excluded from the priority query entirely.

Rate limit handling:
  A Groq ``RateLimitError`` is an infrastructure signal, not an article-
  content problem. It does NOT bump ``attempt_count``. The article
  remains in ``clustered`` state with ``state_error`` recording the
  429; ``enrich_articles`` sets ``result.rate_limited=True`` and the
  orchestrator uses that to stop the enrich drain loop for the current
  cycle. The next cycle picks the article up again.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.config import get_settings
from src.db.models import AnalysisRun, Article, ArticleAnalysis, Outlet
from src.ingestion.enrich_schema import EnrichmentResponse

log = logging.getLogger(__name__)

# Same 3-attempt cap as fetch.py (arch Appendix A). Do not diverge.
MAX_ATTEMPTS = 3

# Prompt files ship with the package.
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Bumped to v2 on 2026-09-24. v1 remains on disk untouched (arch §17 —
# versions are additive, never edited in place). v2 tightens the
# verbatim rules to eliminate the 4 paraphrase-drift patterns observed
# in the Part 2 grounding review.
DEFAULT_PROMPT_VERSION = "enrich_v2"
DEFAULT_TIMEOUT_S = 30.0

# LLM calls are slow and billed; keep default batch small (fetch/embed
# use 100). This is a per-invocation cap, not a per-cycle cap — the
# orchestrator's drain loop (Week 2, when we wire this into run.py) will
# call enrich_articles repeatedly.
DEFAULT_BATCH_LIMIT = 20

# Cap the body sent to the LLM to keep prompt size bounded.
BODY_CHAR_LIMIT = 8000


class LLMClient(Protocol):
    """Minimal chat-completion interface so tests can inject a fake."""

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> str: ...


def _is_rate_limit_error(exc: BaseException) -> bool:
    """True for HTTP 429 / Groq RateLimitError-shaped exceptions.

    Classified by exception class name substring so we don't hard-depend
    on the ``groq`` SDK's exception hierarchy layout (tests inject a
    lookalike class literally named ``RateLimitError``). Also honours
    an explicit ``status_code == 429`` attribute for defence in depth.
    """
    name = type(exc).__name__.lower()
    if "ratelimit" in name:
        return True
    sc = getattr(exc, "status_code", None)
    return sc == 429


@dataclass
class EnrichBatchResult:
    """Return value of :func:`enrich_articles`.

    Iterable as a 2-tuple ``(analyzed, failed_permanent)`` for backwards
    compatibility with existing callers and tests. Also carries the
    ``rate_limited`` flag so the orchestrator can stop the enrich drain
    loop when Groq is refusing calls.
    """

    analyzed: int
    failed_permanent: int
    rate_limited: bool = False

    def __iter__(self) -> Iterator[int]:
        yield self.analyzed
        yield self.failed_permanent


@dataclass
class GroqClient:
    """Lazy-init wrapper around the groq SDK.

    The groq package is imported inside ``__post_init__`` so this module
    imports cleanly in environments without the SDK (e.g. CI without the
    dep, or tests that stub out the LLM). One retry on transient
    network errors; other exceptions propagate to the caller.
    """

    api_key: str
    _client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        from groq import Groq  # local import — see class docstring
        # Never let the api_key end up in a repr or __str__.
        self._client = Groq(api_key=self.api_key, timeout=DEFAULT_TIMEOUT_S)

    def __repr__(self) -> str:  # never leak the key via repr
        return "GroqClient(api_key=<REDACTED>)"

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> str:
        """Chat-complete with response_format=json_object; retry once on
        transient timeout/connection errors.

        A ``RateLimitError`` propagates immediately — the Groq SDK
        already retries 429s internally with Retry-After honouring, so
        a second retry inside this client is wasted work. The caller
        (``enrich_articles``) treats 429s as flow-control, not article
        failures.
        """
        assert self._client is not None
        last_transient: Exception | None = None
        for attempt in (1, 2):
            try:
                resp = self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    timeout=timeout_s,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                # 429s propagate — SDK already retried; extra client
                # retries can't help and only extend runtime.
                if _is_rate_limit_error(exc):
                    raise
                # Classify by exception name so we don't hard-depend on
                # the groq exception hierarchy layout.
                name = type(exc).__name__.lower()
                is_transient = any(
                    tok in name
                    for tok in ("timeout", "connection", "apitimeout",
                                "apiconnection")
                )
                if attempt == 1 and is_transient:
                    log.warning("enrich: transient LLM error, one retry: %s",
                                type(exc).__name__)
                    last_transient = exc
                    continue
                raise
        # Unreachable — the loop either returns or raises above.
        raise last_transient if last_transient else RuntimeError("unreachable")


def _load_prompt(version: str) -> str:
    """Return the text of a versioned prompt file, or raise clearly."""
    path = PROMPTS_DIR / f"{version}.txt"
    if not path.exists():
        raise FileNotFoundError(f"prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if text.strip().startswith("PLACEHOLDER"):
        raise ValueError(f"prompt {version!r} is still a placeholder")
    return text


def _render_prompt(template: str, *, outlet_slug: str, headline: str,
                   body: str) -> str:
    """Fill the {outlet_slug}/{headline}/{body} placeholders in the prompt.

    Uses ``str.replace`` (not ``str.format``) so curly braces in the
    article body don't break rendering.
    """
    return (
        template
        .replace("{outlet_slug}", outlet_slug or "")
        .replace("{headline}", headline or "")
        .replace("{body}", (body or "")[:BODY_CHAR_LIMIT])
    )


def _record_llm_failure(
    session: Session, article: Article, exc: BaseException,
) -> str:
    """Persist an enrichment failure. Returns an outcome tag.

    Outcomes:
      ``"rate_limited"``    — Groq 429; state_error updated but
                              attempt_count and state UNCHANGED. Caller
                              stops the drain loop for this cycle.
      ``"failed_permanent"`` — Third failure; state → failed_analyze.
      ``"retryable"``       — Attempt < MAX_ATTEMPTS; stays clustered,
                              attempt_count bumped by 1.

    Rate limits are treated separately because the failure has nothing
    to do with the article's content. Consuming article-level retry
    budget on infrastructure signals would prematurely burn an article's
    only 3 lives.
    """
    err = f"{type(exc).__name__}: {str(exc)[:800]}"

    if _is_rate_limit_error(exc):
        log.warning("enrich: article_id=%s hit rate limit; NOT bumping "
                    "attempt_count (429 is flow-control, not article "
                    "failure)", article.id)
        session.execute(
            update(Article)
            .where(Article.id == article.id)
            .values(
                state_updated_at=datetime.now(tz=timezone.utc),
                state_error=err[:2000],
            )
        )
        return "rate_limited"

    new_attempts = (article.attempt_count or 0) + 1
    if new_attempts >= MAX_ATTEMPTS:
        log.warning("enrich: %d attempts on article_id=%s → failed_analyze",
                    new_attempts, article.id)
        session.execute(
            update(Article)
            .where(Article.id == article.id)
            .values(
                processing_state="failed_analyze",
                state_updated_at=datetime.now(tz=timezone.utc),
                state_error=err[:2000],
                attempt_count=new_attempts,
            )
        )
        return "failed_permanent"

    log.info("enrich: attempt %d/%d on article_id=%s failed: %s",
             new_attempts, MAX_ATTEMPTS, article.id, err[:120])
    session.execute(
        update(Article)
        .where(Article.id == article.id)
        .values(
            state_updated_at=datetime.now(tz=timezone.utc),
            state_error=err[:2000],
            attempt_count=new_attempts,
        )
    )
    return "retryable"


# ---------------------------------------------------------------------------
# Priority-driven candidate selection (production path)
# ---------------------------------------------------------------------------
# Threshold aligned with compare.MIN_OUTLETS: a story with fewer than 2
# distinct outlets cannot yield a cross-outlet comparison, so paying to
# enrich it now would be wasted budget. Single-outlet stories remain
# clustered indefinitely; they become eligible the moment a second
# outlet joins.
COVERAGE_PRIORITY_MIN_OUTLETS = 2

_PRIORITIZED_SELECT_SQL = text("""
    WITH story_outlets AS (
      SELECT story_id,
             COUNT(DISTINCT outlet_id) AS n_outlets,
             COUNT(*)                  AS n_articles,
             MAX(published_at)         AS latest_published
        FROM articles
       WHERE story_id IS NOT NULL
         AND processing_state IN
             ('clustered', 'analyzed', 'complete')
       GROUP BY story_id
    )
    SELECT a.id                                    AS article_id,
           o.slug                                  AS outlet_slug,
           CASE WHEN sc.story_id IS NOT NULL
                THEN 1 ELSE 2 END                  AS priority_tier
      FROM articles a
      JOIN outlets      o  ON o.id       = a.outlet_id
      JOIN story_outlets so ON so.story_id = a.story_id
      LEFT JOIN story_comparisons sc
             ON sc.story_id = a.story_id
     WHERE a.processing_state = 'clustered'
       AND a.attempt_count < :max_attempts
       AND so.n_outlets >= :min_outlets
     ORDER BY
       -- P1: stories with an existing comparison + fresh clustered coverage
       -- P2: stories that have just become multi-outlet (no comparison yet)
       CASE WHEN sc.story_id IS NOT NULL THEN 1 ELSE 2 END ASC,
       -- Within a tier: strongest coverage signal first
       so.n_outlets       DESC,
       so.n_articles      DESC,
       so.latest_published DESC,
       a.published_at     DESC,
       a.id               ASC
     LIMIT :lim
""")


def _select_clustered_prioritized(
    session: Session, *,
    batch_limit: int,
    story_ids: list[int] | None = None,
) -> list[tuple[int, str]]:
    """Return up to *batch_limit* (article_id, outlet_slug) tuples using
    the coverage-priority ordering. Single-outlet stories are excluded.

    ``story_ids`` (test / manual-retry scope): when given, both the
    ``story_outlets`` CTE and the outer SELECT are restricted to those
    stories. This lets test suites use the production priority path
    against a shared dev-test DB without picking up unrelated real
    coverage. Production callers pass ``None`` and get full ordering.
    """
    if story_ids is None:
        rows = session.execute(
            _PRIORITIZED_SELECT_SQL,
            {
                "lim": batch_limit,
                "max_attempts": MAX_ATTEMPTS,
                "min_outlets": COVERAGE_PRIORITY_MIN_OUTLETS,
            },
        ).all()
    else:
        if not story_ids:
            return []
        ids_sql = ",".join(str(int(i)) for i in story_ids)
        scoped_sql = text(f"""
            WITH story_outlets AS (
              SELECT story_id,
                     COUNT(DISTINCT outlet_id) AS n_outlets,
                     COUNT(*)                  AS n_articles,
                     MAX(published_at)         AS latest_published
                FROM articles
               WHERE story_id IS NOT NULL
                 AND story_id IN ({ids_sql})
                 AND processing_state IN
                     ('clustered', 'analyzed', 'complete')
               GROUP BY story_id
            )
            SELECT a.id                                    AS article_id,
                   o.slug                                  AS outlet_slug,
                   CASE WHEN sc.story_id IS NOT NULL
                        THEN 1 ELSE 2 END                  AS priority_tier
              FROM articles a
              JOIN outlets      o  ON o.id       = a.outlet_id
              JOIN story_outlets so ON so.story_id = a.story_id
              LEFT JOIN story_comparisons sc
                     ON sc.story_id = a.story_id
             WHERE a.processing_state = 'clustered'
               AND a.attempt_count < :max_attempts
               AND so.n_outlets >= :min_outlets
               AND a.story_id IN ({ids_sql})
             ORDER BY
               CASE WHEN sc.story_id IS NOT NULL THEN 1 ELSE 2 END ASC,
               so.n_outlets       DESC,
               so.n_articles      DESC,
               so.latest_published DESC,
               a.published_at     DESC,
               a.id               ASC
             LIMIT :lim
        """)
        rows = session.execute(
            scoped_sql,
            {
                "lim": batch_limit,
                "max_attempts": MAX_ATTEMPTS,
                "min_outlets": COVERAGE_PRIORITY_MIN_OUTLETS,
            },
        ).all()
    return [(int(r.article_id), r.outlet_slug) for r in rows]


def enrich_articles(
    session: Session,
    *,
    llm: LLMClient,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    model_id: str | None = None,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    outlet_id: int | None = None,
    article_ids: list[int] | None = None,
    story_ids: list[int] | None = None,
) -> EnrichBatchResult:
    """Advance up to ``batch_limit`` articles from ``clustered`` → ``analyzed``.

    Returns an :class:`EnrichBatchResult` — iterable as
    ``(analyzed, failed_permanent)`` for backwards compatibility, plus
    ``.rate_limited`` for the orchestrator's drain-loop control.

    ``failed_permanent`` only counts rows that hit the 3-failure cap in
    this call. Rate-limit (429) failures never bump ``attempt_count``
    and never move the article to ``failed_analyze`` — instead
    ``rate_limited`` is set True and the loop stops early so the caller
    can back off.

    A single ``analysis_runs`` row is inserted for the batch (only when
    at least one article is actually processed), recording ``model_id``
    + ``prompt_version`` + ``purpose='enrich'``. Each successful article
    gets one ``article_analysis`` row pointing at that run (latest-wins
    on ``article_analysis.article_id`` PK, per the 2026-09-20 decision).

    Selection:
      - If *outlet_id* OR *article_ids* is given, the caller is doing
        explicit scoped selection (tests / controlled samples). We use
        the simple state='clustered' filter with those constraints and
        NO priority ordering.
      - Otherwise, production selection uses
        :func:`_select_clustered_prioritized` — coverage-priority
        ordering. Single-outlet stories are excluded from the budget;
        they remain in ``clustered`` state indefinitely and become
        eligible the moment a second outlet joins.
      - *story_ids* (optional) narrows the priority-path selection to
        those stories only. Used by tests to keep the priority ordering
        contained to their own fixtures on a shared dev-test DB. Has
        no effect on the filter path.
    """
    model_id = model_id or get_settings().llm_model
    template = _load_prompt(prompt_version)

    # Two selection paths (see docstring): explicit-scope (tests /
    # controlled samples) and priority-driven (production).
    if outlet_id is not None or article_ids is not None:
        q = (
            select(Article, Outlet.slug)
            .join(Outlet, Outlet.id == Article.outlet_id)
            .where(Article.processing_state == "clustered")
        )
        if outlet_id is not None:
            q = q.where(Article.outlet_id == outlet_id)
        if article_ids is not None:
            q = q.where(Article.id.in_(article_ids))
        q = q.order_by(Article.id).limit(batch_limit)
        rows = list(session.execute(q).all())
        candidate_pairs = [(r.Article, r.slug) for r in rows]
    else:
        # Production path — prioritized SELECT + one ORM load per
        # candidate. Prioritized SELECT returns (article_id, outlet_slug)
        # so we round-trip through the ORM for the Article object we
        # already know how to render.
        id_slug = _select_clustered_prioritized(
            session, batch_limit=batch_limit, story_ids=story_ids,
        )
        if not id_slug:
            return EnrichBatchResult(0, 0, rate_limited=False)
        ids_only = [aid for aid, _ in id_slug]
        slug_by_id = {aid: slug for aid, slug in id_slug}
        # Preserve the priority order returned by the SQL.
        articles_by_id = {
            a.id: a
            for a in session.scalars(
                select(Article).where(Article.id.in_(ids_only))
            ).all()
        }
        candidate_pairs = [
            (articles_by_id[aid], slug_by_id[aid])
            for aid in ids_only
            if aid in articles_by_id
        ]

    if not candidate_pairs:
        return EnrichBatchResult(0, 0, rate_limited=False)

    log.info("enrich: %d candidates in state=clustered", len(candidate_pairs))

    # One analysis_runs row per batch. Flush now to get the id; the row
    # commits together with the first article's per-row commit below.
    run = AnalysisRun(
        ran_at=datetime.now(tz=timezone.utc),
        model_id=model_id,
        prompt_version=prompt_version,
        purpose="enrich",
    )
    session.add(run)
    session.flush()
    run_id = run.id

    analyzed = 0
    failed_permanent = 0
    rate_limited = False

    for article, outlet_slug in candidate_pairs:
        prompt = _render_prompt(template,
                                outlet_slug=outlet_slug,
                                headline=article.headline,
                                body=article.full_text or "")
        try:
            raw = llm.complete(model=model_id, prompt=prompt,
                               timeout_s=timeout_s)
            data = json.loads(raw)
            validated = EnrichmentResponse.model_validate(data)
        except Exception as exc:
            outcome = _record_llm_failure(session, article, exc)
            session.commit()
            if outcome == "failed_permanent":
                failed_permanent += 1
            elif outcome == "rate_limited":
                # Stop the batch immediately — Groq is refusing calls;
                # further attempts this cycle are wasted. The article
                # itself is untouched (attempt_count unchanged).
                rate_limited = True
                break
            continue

        # UPSERT article_analysis — latest-wins on article_id.
        ins = pg_insert(ArticleAnalysis).values(
            article_id=article.id,
            analysis_run_id=run_id,
            framing_score=validated.framing_score,
            framing_label=validated.framing_label,
            framing_confidence=validated.framing_confidence,
            headline_sentiment=validated.headline_sentiment,
            body_sentiment=validated.body_sentiment,
            key_themes=list(validated.key_themes),
            entities=validated.entities.model_dump(),
            quoted_sources=[qs.model_dump() for qs in validated.quoted_sources],
            source_distribution=validated.source_distribution.model_dump(),
            evidence_snippets=list(validated.evidence_snippets),
            analyzed_at=datetime.now(tz=timezone.utc),
        )
        ins = ins.on_conflict_do_update(
            index_elements=["article_id"],
            set_={
                "analysis_run_id":     ins.excluded.analysis_run_id,
                "framing_score":       ins.excluded.framing_score,
                "framing_label":       ins.excluded.framing_label,
                "framing_confidence":  ins.excluded.framing_confidence,
                "headline_sentiment":  ins.excluded.headline_sentiment,
                "body_sentiment":      ins.excluded.body_sentiment,
                "key_themes":          ins.excluded.key_themes,
                "entities":            ins.excluded.entities,
                "quoted_sources":      ins.excluded.quoted_sources,
                "source_distribution": ins.excluded.source_distribution,
                "evidence_snippets":   ins.excluded.evidence_snippets,
                "analyzed_at":         ins.excluded.analyzed_at,
            },
        )
        session.execute(ins)
        session.execute(
            update(Article)
            .where(Article.id == article.id)
            .values(
                processing_state="analyzed",
                state_updated_at=datetime.now(tz=timezone.utc),
                state_error=None,
                attempt_count=0,
            )
        )
        analyzed += 1
        session.commit()

    log.info(
        "enrich: analyzed=%d failed_permanent=%d run_id=%s rate_limited=%s",
        analyzed, failed_permanent, run_id, rate_limited,
    )
    return EnrichBatchResult(
        analyzed=analyzed,
        failed_permanent=failed_permanent,
        rate_limited=rate_limited,
    )
