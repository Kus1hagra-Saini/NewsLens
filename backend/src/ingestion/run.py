"""Ingestion orchestrator.

Entry points:
    python -m src.ingestion.run              # one full cycle
    python -m src.ingestion.run --once       # (alias for above; kept for
                                             #  arch §16 command)
    python -m src.ingestion.run --phase phase_1 [--phase phase_2 ...]
    python -m src.ingestion.run --hash-embedder   # skip MiniLM (CI/dev)
    python -m src.ingestion.run --skip-cluster    # discover+extract+embed only
    python -m src.ingestion.run --skip-embed      # discover+extract only
    python -m src.ingestion.run --skip-enrich     # skip LLM enrich + compare
    python -m src.ingestion.run --skip-compare    # run enrich, skip compare

For every cycle the orchestrator opens an `ingestion_runs` row with
status='running', walks each active outlet through
discover → extract → embed → cluster → enrich → compare, records
rolling counts, and closes the row with status='success' (or 'failed'
if the whole cycle raised an unexpected exception).

Failures inside a stage — a per-article extract 404, a per-article LLM
timeout, a per-story compare failure — are recorded on the article's
`state_error` + `attempt_count` (extract/enrich) or logged and skipped
(compare, which has no per-story attempt column). They do NOT fail the
run — the next cycle picks the rows up again. That matches
architecture §10.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings
from src.db.models import IngestionRun, Outlet
from src.ingestion.cluster import cluster_articles
from src.ingestion.compare import compare_stories
from src.ingestion.embed import Embedder, HashEmbedder, MiniLMEmbedder, embed_articles
from src.ingestion.enrich import GroqClient, LLMClient, enrich_articles
from src.ingestion.fetch import HttpxFetcher, discover_articles, extract_articles
from src.ingestion.log import setup_logging
from src.ingestion.outlets import load_outlets

log = logging.getLogger(__name__)


class _CountingLLM:
    """Thin wrapper around an ``LLMClient`` that tallies ``.complete()`` calls.

    Enrichment reports (analyzed, failed_permanent) which UNDER-counts
    the actual LLM traffic (an article that failed on attempt 1 or 2
    doesn't show up in either). Counting calls at the client layer
    gives an accurate ``llm_calls`` figure for the ``ingestion_runs``
    row.
    """

    def __init__(self, inner: LLMClient):
        self._inner = inner
        self.count = 0

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> str:
        self.count += 1
        return self._inner.complete(model=model, prompt=prompt, timeout_s=timeout_s)


def run_once(
    *,
    phases: list[str],
    embedder: Embedder,
    triggered_by: str = "manual",
    skip_embed: bool = False,
    skip_cluster: bool = False,
    skip_enrich: bool = False,
    skip_compare: bool = False,
    fetcher_factory=HttpxFetcher,
    llm_factory: Callable[[], LLMClient] | None = None,
) -> int:
    """Run one complete ingestion cycle. Returns 0 on success, 1 on fail.

    ``llm_factory`` is called at most once to produce the LLM client
    used for both enrichment and comparison. Tests inject a fake here.
    In production it defaults to ``GroqClient(api_key=...)`` when the
    ``GROQ_API_KEY`` setting is populated; if the key is missing, the
    enrich and compare stages are silently skipped (with a warning
    logged) — the earlier stages still run so pipeline development
    without an API key stays possible.
    """
    settings = get_settings()
    if not settings.ingestion_enabled:
        log.warning("INGESTION_ENABLED=false — recording a skipped run and exiting")
        _record_skipped(triggered_by)
        return 0

    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)

    # Open the ingestion_runs row FIRST so that even a very early
    # exception is recorded — the outer `except` needs `run_id`.
    with Session_() as session:
        run = IngestionRun(
            started_at=datetime.now(tz=timezone.utc),
            triggered_by=triggered_by,
            status="running",
        )
        session.add(run)
        session.commit()
        run_id = run.id

    log.info("=== ingestion run id=%s started (phases=%s) ===", run_id, phases)

    # Rolling counters. Schema-supported fields (discovered / inserted /
    # failed / llm_calls) flow into _close_run. Extras (analyzed,
    # compared) are for the log line only — no schema change.
    totals = {
        "discovered": 0, "inserted": 0, "failed": 0,
        "analyzed":   0, "compared":  0,
        "llm_calls":  0,
    }

    # Build the LLM client once and share between enrich + compare.
    # A missing GROQ_API_KEY or a construction failure downgrades to
    # "no LLM" instead of crashing the run — the earlier stages still
    # add value and the next run can pick up the LLM work.
    llm: _CountingLLM | None = None
    llm_needed = not (skip_enrich and skip_compare)
    if llm_needed:
        try:
            if llm_factory is not None:
                inner = llm_factory()
            elif settings.groq_api_key:
                inner = GroqClient(api_key=settings.groq_api_key)
            else:
                inner = None
                log.warning(
                    "run: GROQ_API_KEY not set — skipping enrich + compare stages"
                )
            if inner is not None:
                llm = _CountingLLM(inner)
        except Exception as exc:
            log.error("run: LLM client init failed (%s) — skipping enrich + compare",
                      type(exc).__name__)
            llm = None

    try:
        with Session_() as session:
            outlets = _load_active_outlets(session, phases)
            if not outlets:
                log.warning("run: no active outlets — nothing to do")
            fetcher = fetcher_factory()

            try:
                # ------------------------------------------------------------
                # STAGE 1: RSS discovery — outlet-by-outlet.
                # A crash on one outlet must not abort the run.
                # ------------------------------------------------------------
                for outlet in outlets:
                    try:
                        new = discover_articles(session, outlet, fetcher=fetcher)
                        totals["discovered"] += new
                        totals["inserted"] += new
                    except Exception as exc:
                        log.error("discover: %s crashed: %s", outlet.slug, exc)
                        totals["failed"] += 1

                # ------------------------------------------------------------
                # STAGE 2: extraction — drain all discovered articles.
                # Each call advances up to batch_limit (default 100) rows;
                # loop until no progress so a single --once run processes
                # every eligible article.
                # ------------------------------------------------------------
                while True:
                    extracted, failed_x = extract_articles(session, fetcher=fetcher)
                    totals["failed"] += failed_x
                    if extracted == 0 and failed_x == 0:
                        break

                # ------------------------------------------------------------
                # STAGE 3: embeddings — drain all extracted articles.
                # ------------------------------------------------------------
                if not skip_embed:
                    while embed_articles(session, embedder=embedder) > 0:
                        pass

                # ------------------------------------------------------------
                # STAGE 4: clustering — drain all embedded articles.
                # ------------------------------------------------------------
                if not skip_cluster and not skip_embed:
                    while cluster_articles(session).articles_clustered > 0:
                        pass

                # ------------------------------------------------------------
                # STAGE 5: LLM enrichment — bounded by
                # settings.llm_enrich_budget_per_run. Per-article failures
                # still increment attempt_count in enrich.py and move to
                # failed_analyze after 3 strikes. A Groq 429 does NOT
                # bump attempt_count (see enrich._record_llm_failure); it
                # sets rate_limited=True and we break the drain for this
                # cycle so we do not hammer the API. Any UNEXPECTED
                # batch-level exception is caught so it doesn't crash the
                # whole ingestion run.
                # ------------------------------------------------------------
                if (llm is not None
                        and not skip_enrich
                        and not skip_cluster
                        and not skip_embed):
                    enrich_budget = settings.llm_enrich_budget_per_run
                    try:
                        while enrich_budget > 0:
                            take = min(20, enrich_budget)
                            result = enrich_articles(
                                session, llm=llm, batch_limit=take,
                            )
                            totals["analyzed"] += result.analyzed
                            totals["failed"] += result.failed_permanent
                            enrich_budget -= (result.analyzed
                                              + result.failed_permanent)
                            if result.rate_limited:
                                log.warning(
                                    "enrich: rate-limited by Groq; stopping "
                                    "enrich drain for this cycle "
                                    "(remaining budget=%d)",
                                    enrich_budget,
                                )
                                break
                            if (result.analyzed == 0
                                    and result.failed_permanent == 0):
                                # No eligible work left this cycle.
                                break
                    except Exception as exc:
                        log.error("enrich: batch crashed, "
                                  "continuing with compare stage: %s",
                                  exc, exc_info=True)

                # ------------------------------------------------------------
                # STAGE 6: story comparison — bounded by
                # settings.llm_compare_budget_per_run. compare_stories has
                # no per-story attempt_count; failed comparisons leave
                # articles in 'analyzed' for retry. A batch-level exception
                # is caught so it doesn't crash the run.
                # ------------------------------------------------------------
                if (llm is not None
                        and not skip_compare
                        and not skip_enrich
                        and not skip_cluster
                        and not skip_embed):
                    compare_budget = settings.llm_compare_budget_per_run
                    try:
                        while compare_budget > 0:
                            take = min(10, compare_budget)
                            compared, _ = compare_stories(
                                session, llm=llm, batch_limit=take,
                            )
                            totals["compared"] += compared
                            compare_budget -= compared
                            if compared == 0:
                                break
                    except Exception as exc:
                        log.error("compare: batch crashed: %s", exc, exc_info=True)

            finally:
                if hasattr(fetcher, "close"):
                    fetcher.close()

        if llm is not None:
            totals["llm_calls"] = llm.count

        _close_run(engine, run_id, "success", totals, error=None)
        log.info("=== ingestion run id=%s success %s ===", run_id, totals)
        return 0

    except Exception:
        tb = traceback.format_exc()
        log.error("run: cycle crashed:\n%s", tb)
        if llm is not None:
            totals["llm_calls"] = llm.count
        _close_run(engine, run_id, "failed", totals, error=tb[:4000])
        return 1
    finally:
        engine.dispose()


def _load_active_outlets(session: Session, phases: list[str]) -> list[Outlet]:
    """Return active outlets whose slug matches any phase in outlets.yaml.

    Reads the yaml to know which slugs belong to which phase; that keeps
    the DB free of phase metadata.
    """
    specs = load_outlets(phases)
    slugs = [s.slug for s in specs]
    if not slugs:
        return []
    q = (
        select(Outlet)
        .where(Outlet.slug.in_(slugs))
        .where(Outlet.active.is_(True))
    )
    return list(session.scalars(q))


def _close_run(engine, run_id: int, status: str, totals: dict, error: str | None) -> None:
    from sqlalchemy import update
    with engine.begin() as conn:
        conn.execute(
            update(IngestionRun).where(IngestionRun.id == run_id).values(
                completed_at=datetime.now(tz=timezone.utc),
                articles_discovered=totals.get("discovered", 0),
                articles_inserted=totals.get("inserted", 0),
                articles_failed=totals.get("failed", 0),
                llm_calls=totals.get("llm_calls", 0),
                status=status,
                error=error,
            )
        )


def _record_skipped(triggered_by: str) -> None:
    """Record a skipped run when INGESTION_ENABLED=false."""
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(
            IngestionRun.__table__.insert().values(
                started_at=datetime.now(tz=timezone.utc),
                completed_at=datetime.now(tz=timezone.utc),
                triggered_by=triggered_by,
                articles_discovered=0,
                articles_inserted=0,
                articles_failed=0,
                llm_calls=0,
                status="skipped",
                error=None,
            )
        )
    engine.dispose()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one NewsLens ingestion cycle.")
    ap.add_argument("--once", action="store_true",
                    help="One cycle then exit (default; kept for §16 command).")
    ap.add_argument("--phase", action="append", dest="phases",
                    help="Phase key from outlets.yaml. Repeat for multiple. "
                         "Default: phase_1")
    ap.add_argument("--hash-embedder", action="store_true",
                    help="Use deterministic HashEmbedder instead of MiniLM. "
                         "For CI or when the model download is unavailable.")
    ap.add_argument("--skip-embed", action="store_true",
                    help="Skip the embed + cluster + enrich + compare stages.")
    ap.add_argument("--skip-cluster", action="store_true",
                    help="Embed but skip clustering + enrich + compare.")
    ap.add_argument("--skip-enrich", action="store_true",
                    help="Skip the LLM enrichment stage (and compare, which depends on it).")
    ap.add_argument("--skip-compare", action="store_true",
                    help="Run enrichment but skip the story-comparison stage.")
    ap.add_argument("--triggered-by", default="manual",
                    choices=["cron", "manual", "backfill"])
    args = ap.parse_args()

    setup_logging()

    phases = args.phases or ["phase_1"]

    if args.hash_embedder:
        log.warning("using HashEmbedder — vectors are NOT real semantic embeddings")
        embedder: Embedder = HashEmbedder()
    else:
        try:
            embedder = MiniLMEmbedder()
        except Exception as exc:
            log.error("MiniLM unavailable (%s). "
                      "Re-run with --hash-embedder if this is a dev/CI run.",
                      exc)
            return 2

    return run_once(
        phases=phases,
        embedder=embedder,
        triggered_by=args.triggered_by,
        skip_embed=args.skip_embed,
        skip_cluster=args.skip_cluster,
        skip_enrich=args.skip_enrich,
        skip_compare=args.skip_compare,
    )


if __name__ == "__main__":
    sys.exit(main())
