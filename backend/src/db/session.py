"""Async SQLAlchemy engine + session factory.

One engine per process, created lazily so tests can swap DATABASE_URL
before the first call.
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
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an AsyncSession, closes it after the request."""
    async with _sessionmaker()() as session:
        yield session
