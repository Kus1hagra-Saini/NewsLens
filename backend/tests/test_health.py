"""Smoke tests: /health and the ORM model set.

Uses a monkeypatched environment so importing src.main does not require a
real DATABASE_URL, GROQ_API_KEY, or LLM_MODEL at CI startup.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@localhost/x")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")

    # Clear cached settings so the fixture-provided env is picked up.
    from src.config import get_settings

    get_settings.cache_clear()

    from src.main import app

    return TestClient(app)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_models_import() -> None:
    """Guard against a future models.py regression that would prevent
    alembic env.py from loading Base.metadata for autogenerate compare.
    Also asserts we have exactly the 9 tables from architecture §9."""
    from src.db.models import Base

    expected = {
        "outlets",
        "stories",
        "analysis_runs",
        "articles",
        "article_analysis",
        "story_comparisons",
        "story_overrides",
        "ingestion_runs",
        "eval_labels",
    }
    assert set(Base.metadata.tables.keys()) == expected



# ---------------------------------------------------------------------------
# DSN normalization — psycopg2 must never be selected. See src/config.py.
# ---------------------------------------------------------------------------
import pytest as _pt


@_pt.mark.parametrize("raw, expected", [
    ("postgresql://u:p@h/d?sslmode=require",
     "postgresql+psycopg://u:p@h/d?sslmode=require"),
    ("postgres://u:p@h/d",
     "postgresql+psycopg://u:p@h/d"),
    ("postgresql+asyncpg://u:p@h/d?ssl=require",
     "postgresql+psycopg://u:p@h/d?ssl=require"),
    ("postgresql+psycopg://u:p@h/d?sslmode=require",
     "postgresql+psycopg://u:p@h/d?sslmode=require"),
])
def test_to_sync_dsn_normalizes_every_accepted_shape(raw, expected):
    from src.config import _to_sync_dsn
    assert _to_sync_dsn(raw) == expected


@_pt.mark.parametrize("raw, expected", [
    ("postgresql://u:p@h/d?sslmode=require",
     "postgresql+asyncpg://u:p@h/d?sslmode=require"),
    ("postgres://u:p@h/d",
     "postgresql+asyncpg://u:p@h/d"),
    ("postgresql+asyncpg://u:p@h/d?ssl=require",
     "postgresql+asyncpg://u:p@h/d?ssl=require"),
    ("postgresql+psycopg://u:p@h/d?sslmode=require",
     "postgresql+asyncpg://u:p@h/d?sslmode=require"),
])
def test_to_async_dsn_normalizes_every_accepted_shape(raw, expected):
    from src.config import _to_async_dsn
    assert _to_async_dsn(raw) == expected


def test_settings_sync_and_async_properties(monkeypatch):
    """End-to-end: bare postgresql:// URL selects psycopg (sync) and
    asyncpg (async), not psycopg2."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/d?sslmode=require")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "x")
    from src.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.sync_database_url == "postgresql+psycopg://u:p@h/d?sslmode=require"
    assert s.async_database_url == "postgresql+asyncpg://u:p@h/d?sslmode=require"
