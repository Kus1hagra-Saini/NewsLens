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
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select, update
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

DEFAULT_PROMPT_VERSION = "enrich_v1"
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
        """Chat-complete with response_format=json_object; retry once on transient errors."""
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


def _record_llm_failure(session: Session, article: Article, error: str) -> bool:
    """Bump attempt_count; on the 3rd failure move to failed_analyze.

    Same shape as fetch._record_failure but hard-coded to the enrich
    stage (clustered → failed_analyze). Returns True iff the row moved
    to failed_analyze in this call. The caller controls the transaction.
    """
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
                state_error=error[:2000],
                attempt_count=new_attempts,
            )
        )
        return True

    log.info("enrich: attempt %d/%d on article_id=%s failed: %s",
             new_attempts, MAX_ATTEMPTS, article.id, error[:120])
    session.execute(
        update(Article)
        .where(Article.id == article.id)
        .values(
            state_updated_at=datetime.now(tz=timezone.utc),
            state_error=error[:2000],
            attempt_count=new_attempts,
        )
    )
    return False


def enrich_articles(
    session: Session,
    *,
    llm: LLMClient,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    model_id: str | None = None,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    outlet_id: int | None = None,
) -> tuple[int, int]:
    """Advance up to ``batch_limit`` articles from ``clustered`` → ``analyzed``.

    Returns ``(analyzed, failed_permanent)`` — ``failed_permanent`` only
    counts rows that hit the 3-failure cap in this call.

    A single ``analysis_runs`` row is inserted for the batch, recording
    ``model_id`` + ``prompt_version`` + ``purpose='enrich'``. Each
    successful article gets one ``article_analysis`` row pointing at
    that run (latest-wins on ``article_analysis.article_id`` PK, per the
    2026-09-20 decision).

    If *outlet_id* is given, only articles belonging to that outlet are
    considered. This is useful in tests that share a database with real
    ingestion data. Mirrors the same-named parameter on
    ``extract_articles`` in ``fetch.py``.
    """
    model_id = model_id or get_settings().llm_model
    template = _load_prompt(prompt_version)

    q = (
        select(Article, Outlet.slug)
        .join(Outlet, Outlet.id == Article.outlet_id)
        .where(Article.processing_state == "clustered")
    )
    if outlet_id is not None:
        q = q.where(Article.outlet_id == outlet_id)
    q = q.order_by(Article.id).limit(batch_limit)
    rows = list(session.execute(q).all())
    if not rows:
        return 0, 0

    log.info("enrich: %d candidates in state=clustered", len(rows))

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

    for article, outlet_slug in rows:
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
            err = f"{type(exc).__name__}: {str(exc)[:800]}"
            if _record_llm_failure(session, article, err):
                failed_permanent += 1
            session.commit()
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

    log.info("enrich: analyzed=%d failed_permanent=%d run_id=%s",
             analyzed, failed_permanent, run_id)
    return analyzed, failed_permanent
