"""Async SQLAlchemy engine + session factory.

One engine per process, created lazily so tests can swap DATABASE_URL
before the first call.

SSL: Neon's DSN carries ``sslmode=require`` (a libpq-only param) which
asyncpg does not accept. ``src.config`` strips it from the URL and
exposes the equivalent asyncpg kwarg via
``Settings.async_connect_args``; we hand that dict to
``create_async_engine(connect_args=...)`` so SSL is enforced through
the driver's own vocabulary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings


@lru_cache(maxsize=1)
def _engine():
    settings = get_settings()
    return create_async_engine(
        settings.async_database_url,
        pool_pre_ping=True,
        connect_args=settings.async_connect_args,
    )


@lru_cache(maxsize=1)
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an AsyncSession, closes it after the request."""
    async with _sessionmaker()() as session:
        yield session
