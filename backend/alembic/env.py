"""Alembic environment.

Reads DATABASE_URL from the environment (via src.config) and rewrites the
driver from asyncpg to psycopg for Alembic's sync operations.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config import get_settings
from src.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _sync_url() -> str:
    """Return DATABASE_URL rewritten for the sync psycopg 3 driver.

    Delegates to src.config._to_sync_dsn so alembic and the ingestion
    pipeline share one canonical URL-normalization path. Falls back to
    the raw DATABASE_URL env var when Settings hasn't been loaded (some
    alembic invocations bypass .env loading).
    """
    from src.config import _to_sync_dsn
    raw = os.environ.get("DATABASE_URL") or get_settings().database_url
    return _to_sync_dsn(raw)


target_metadata = Base.metadata

# Indexes that live only in the initial migration (DESC-ordered btree,
# pgvector ivfflat, tsvector gin). SQLAlchemy autogenerate cannot
# round-trip these expression forms cleanly, so excluding them from the
# compare avoids spurious `alembic check` drift while still creating and
# dropping them via the migration.
_MIGRATION_ONLY_INDEXES = {
    "ix_articles_outlet_published",
    "ix_articles_embedding_ivfflat",
    "ix_articles_fts_gin",
    "ix_stories_last_seen_at_desc",
    "ix_ingestion_runs_started_at_desc",
}


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "index" and name in _MIGRATION_ONLY_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
