"""Ingestion orchestrator.

Entry points:
    python -m src.ingestion.run              # one full cycle
    python -m src.ingestion.run --once       # (alias for above; kept for
                                             #  arch §16 command)
    python -m src.ingestion.run --phase phase_1 [--phase phase_2 ...]
    python -m src.ingestion.run --hash-embedder   # skip MiniLM (CI/dev)
    python -m src.ingestion.run --skip-cluster    # discover+extract+embed only
    python -m src.ingestion.run --skip-embed      # discover+extract only

For every cycle the orchestrator opens an `ingestion_runs` row with
status='running', walks each active outlet through discover →
extract → embed → cluster, records rolling counts, and closes the row
with status='success' (or 'failed' if the whole cycle raised).

Failures on individual articles are recorded on those rows' state_error
and attempt_count. They do NOT fail the run — the next cycle picks them
up. That matches architecture §10.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings
from src.db.models import IngestionRun, Outlet
from src.ingestion.cluster import cluster_articles
from src.ingestion.embed import Embedder, HashEmbedder, MiniLMEmbedder, embed_articles
from src.ingestion.fetch import HttpxFetcher, discover_articles, extract_articles
from src.ingestion.log import setup_logging
from src.ingestion.outlets import load_outlets

log = logging.getLogger(__name__)


def run_once(
    *,
    phases: list[str],
    embedder: Embedder,
    triggered_by: str = "manual",
    skip_embed: bool = False,
    skip_cluster: bool = False,
    fetcher_factory=HttpxFetcher,
) -> int:
    """Run one complete ingestion cycle. Returns 0 on success, 1 on fail."""
    settings = get_settings()
    if not settings.ingestion_enabled:
        log.warning("INGESTION_ENABLED=false — recording a skipped run and exiting")
        _record_skipped(triggered_by)
        return 0

    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)

    # Open ingestion_runs row
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

    totals = {"discovered": 0, "inserted": 0, "failed": 0}
    try:
        with Session_() as session:
            outlets = _load_active_outlets(session, phases)
            if not outlets:
                log.warning("run: no active outlets — nothing to do")
            fetcher = fetcher_factory()

            try:
                # STAGE 1: RSS discovery — outlet-by-outlet
                for outlet in outlets:
                    try:
                        new = discover_articles(session, outlet, fetcher=fetcher)
                        totals["discovered"] += new
                        totals["inserted"] += new
                    except Exception as exc:
                        log.error("discover: %s crashed: %s", outlet.slug, exc)
                        totals["failed"] += 1

                # STAGE 2: extraction — drain all discovered articles.
                # Each call advances up to batch_limit (default 100)
                # rows; loop until no more progress is made so a single
                # --once run processes every eligible article.
                while True:
                    extracted, failed_x = extract_articles(session, fetcher=fetcher)
                    totals["failed"] += failed_x
                    if extracted == 0 and failed_x == 0:
                        break

                # STAGE 3: embeddings — drain all extracted articles
                if not skip_embed:
                    while embed_articles(session, embedder=embedder) > 0:
                        pass

                # STAGE 4: clustering — drain all embedded articles
                if not skip_cluster and not skip_embed:
                    while cluster_articles(session).articles_clustered > 0:
                        pass

            finally:
                if hasattr(fetcher, "close"):
                    fetcher.close()

        _close_run(engine, run_id, "success", totals, error=None)
        log.info("=== ingestion run id=%s success %s ===", run_id, totals)
        return 0

    except Exception:
        tb = traceback.format_exc()
        log.error("run: cycle crashed:\n%s", tb)
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
                llm_calls=0,   # LLM enrichment lands in the next feature group
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
                    help="Skip the embed + cluster stages (extraction only).")
    ap.add_argument("--skip-cluster", action="store_true",
                    help="Embed but skip clustering.")
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
    )


if __name__ == "__main__":
    sys.exit(main())
