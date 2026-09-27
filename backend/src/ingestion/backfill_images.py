"""One-shot resumable backfill for articles.image_url.

Walks every article whose ``image_url IS NULL`` (in oldest-first
order, so the first pass covers the historical backlog before catching
up to today), downloads the article HTML, extracts an ``og:image`` /
``twitter:image``, and writes the resulting URL back. Nothing else on
the row is touched — no state transitions, no attempt counter change,
no re-extraction of the article body.

Safe to run multiple times. Rows that already carry an image are
skipped by the SQL query, so a re-run only revisits articles the last
pass failed on. Failures are logged and moved past — they never crash
the loop.

Usage:

    python -m src.ingestion.backfill_images                 # default batch
    python -m src.ingestion.backfill_images --limit 500     # smaller run
    python -m src.ingestion.backfill_images --sleep 1.0     # slower pacing
    python -m src.ingestion.backfill_images --outlet ndtv   # scoped

The default rate limit is 0.5 s between requests so we don't hammer
any single outlet. Consider raising it for big backfills, and setting
``--outlet`` to spread requests across days.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings
from src.db.models import Article, Outlet
from src.ingestion.fetch import HttpxFetcher
from src.ingestion.image_extraction import image_url_from_html
from src.ingestion.log import setup_logging

log = logging.getLogger(__name__)


@dataclass
class BackfillStats:
    scanned: int = 0
    updated: int = 0
    no_image: int = 0
    http_failed: int = 0
    parse_failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "updated": self.updated,
            "no_image": self.no_image,
            "http_failed": self.http_failed,
            "parse_failed": self.parse_failed,
        }


def backfill_images(
    *,
    limit: int = 200,
    sleep_s: float = 0.5,
    outlet_slug: str | None = None,
    fetcher: HttpxFetcher | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> BackfillStats:
    """Fill in image_url for up to ``limit`` articles that still lack one.

    ``fetcher`` and ``session_factory`` are injectable for tests. In
    production both come from the shared config.
    """
    stats = BackfillStats()

    owns_fetcher = False
    if fetcher is None:
        fetcher = HttpxFetcher()
        owns_fetcher = True

    owns_engine = False
    if session_factory is None:
        engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        owns_engine = True
    else:
        engine = None

    try:
        with session_factory() as session:
            q = (
                select(Article.id, Article.url)
                .where(Article.image_url.is_(None))
                .order_by(Article.published_at.asc(), Article.id.asc())
                .limit(limit)
            )
            if outlet_slug:
                # Resolve outlet id once so the WHERE stays cheap.
                oid = session.scalar(
                    select(Outlet.id).where(Outlet.slug == outlet_slug)
                )
                if oid is None:
                    log.error("no outlet with slug=%s — nothing to backfill", outlet_slug)
                    return stats
                q = q.where(Article.outlet_id == oid)

            rows = session.execute(q).all()
            log.info("backfill: %d candidate articles (limit=%d)", len(rows), limit)

            for i, (article_id, article_url) in enumerate(rows):
                stats.scanned += 1
                try:
                    resp = fetcher.get(article_url)
                except Exception as exc:
                    log.info(
                        "backfill: HTTP failed article_id=%s: %s",
                        article_id, exc,
                    )
                    stats.http_failed += 1
                else:
                    if resp.status_code != 200:
                        log.info(
                            "backfill: HTTP %s for article_id=%s",
                            resp.status_code, article_id,
                        )
                        stats.http_failed += 1
                    else:
                        img: str | None = None
                        try:
                            img = image_url_from_html(
                                resp.text, base_url=article_url,
                            )
                        except Exception as exc:
                            log.info(
                                "backfill: parse failed article_id=%s: %s",
                                article_id, exc,
                            )
                            stats.parse_failed += 1

                        if img:
                            session.execute(
                                update(Article)
                                .where(Article.id == article_id)
                                # Only touch image_url — never disturb
                                # processing_state or attempt_count.
                                .values(image_url=img)
                            )
                            session.commit()
                            stats.updated += 1
                        else:
                            stats.no_image += 1

                # Rate-limit between requests, but skip the sleep on
                # the last iteration.
                if sleep_s > 0 and i + 1 < len(rows):
                    time.sleep(sleep_s)
    finally:
        if owns_fetcher:
            fetcher.close()
        if owns_engine and engine is not None:
            engine.dispose()

    log.info("backfill: %s", stats.as_dict())
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Backfill articles.image_url from og:image / twitter:image.",
    )
    ap.add_argument("--limit", type=int, default=200,
                    help="Max articles to process this run (default 200).")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Seconds to sleep between requests (default 0.5).")
    ap.add_argument("--outlet", type=str, default=None,
                    help="Scope to a single outlet slug (e.g. 'ndtv').")
    args = ap.parse_args()

    setup_logging()
    stats = backfill_images(
        limit=args.limit,
        sleep_s=args.sleep,
        outlet_slug=args.outlet,
    )
    log.info("done: %s", stats.as_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
