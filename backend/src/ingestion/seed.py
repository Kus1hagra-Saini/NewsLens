"""Idempotent outlet seeding.

`python -m src.ingestion.seed` upserts every outlet in `outlets.yaml`
(Phase-1 by default) into the `outlets` table. Safe to run repeatedly:
does not create duplicates, does not clobber columns that would need
manual review (logo_url is only set when the yaml provides one).
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import get_settings
from src.db.models import Outlet
from src.ingestion.log import setup_logging
from src.ingestion.outlets import OutletSpec, load_outlets

log = logging.getLogger(__name__)


def seed_outlets(specs: list[OutletSpec]) -> tuple[int, int]:
    """Upsert `specs` into outlets. Returns (inserted, updated) counts."""
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    inserted = 0
    updated = 0
    with engine.begin() as conn:
        for spec in specs:
            existing = conn.execute(
                select(Outlet.id, Outlet.rss_url, Outlet.website, Outlet.name)
                .where(Outlet.slug == spec.slug)
            ).first()
            if existing is None:
                stmt = pg_insert(Outlet).values(
                    name=spec.name,
                    slug=spec.slug,
                    rss_url=spec.rss_url,
                    website=spec.website,
                    logo_url=spec.logo_url,
                    active=True,
                )
                conn.execute(stmt)
                inserted += 1
                log.info("seeded outlet slug=%s", spec.slug)
            else:
                # Update only when a metadata field changed.
                needs_update = (
                    existing.rss_url != spec.rss_url
                    or existing.website != spec.website
                    or existing.name != spec.name
                )
                if needs_update:
                    conn.execute(
                        Outlet.__table__.update()
                        .where(Outlet.slug == spec.slug)
                        .values(
                            name=spec.name,
                            rss_url=spec.rss_url,
                            website=spec.website,
                        )
                    )
                    updated += 1
                    log.info("updated outlet slug=%s", spec.slug)
    engine.dispose()
    return inserted, updated


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed outlets from outlets.yaml.")
    ap.add_argument("--phases", nargs="+", default=["phase_1"],
                    help="One or more phase keys from outlets.yaml.")
    args = ap.parse_args()

    setup_logging()
    specs = load_outlets(args.phases)
    if not specs:
        log.error("no outlets found for phases=%s", args.phases)
        return 1

    inserted, updated = seed_outlets(specs)
    log.info("seed complete: inserted=%d updated=%d unchanged=%d",
             inserted, updated, len(specs) - inserted - updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
