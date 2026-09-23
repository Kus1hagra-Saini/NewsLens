"""Smoke tests: /health, ORM model set, and DSN normalization.

DSN tests are asymmetric on purpose:
  * The SYNC path (psycopg 3, wraps libpq) preserves every accepted
    query param including sslmode and channel_binding.
  * The ASYNC path (asyncpg) STRIPS the libpq-only params sslmode and
    channel_binding from the URL, and the SSL requirement travels via
    ``Settings.async_connect_args`` instead. This is enforced because a
    real asyncpg connect() raises TypeError on unknown kwargs.

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


# ------ SYNC path — libpq params are preserved verbatim -------------------
@_pt.mark.parametrize("raw, expected", [
    ("postgresql://u:p@h/d?sslmode=require",
     "postgresql+psycopg://u:p@h/d?sslmode=require"),
    ("postgres://u:p@h/d",
     "postgresql+psycopg://u:p@h/d"),
    ("postgresql+asyncpg://u:p@h/d?ssl=require",
     "postgresql+psycopg://u:p@h/d?ssl=require"),
    ("postgresql+psycopg://u:p@h/d?sslmode=require",
     "postgresql+psycopg://u:p@h/d?sslmode=require"),
    # Neon-shaped URL — sslmode + channel_binding survive on the sync path.
    ("postgresql://u:p@h/d?sslmode=require&channel_binding=require",
     "postgresql+psycopg://u:p@h/d?sslmode=require&channel_binding=require"),
])
def test_to_sync_dsn_normalizes_every_accepted_shape(raw, expected):
    from src.config import _to_sync_dsn
    assert _to_sync_dsn(raw) == expected


# ------ ASYNC path — libpq params are STRIPPED ----------------------------
@_pt.mark.parametrize("raw, expected", [
    # No query params — unchanged behaviour, just dialect rewrite.
    ("postgresql://u:p@h/d",
     "postgresql+asyncpg://u:p@h/d"),
    ("postgres://u:p@h/d",
     "postgresql+asyncpg://u:p@h/d"),
    ("postgresql+asyncpg://u:p@h/d",
     "postgresql+asyncpg://u:p@h/d"),
    ("postgresql+psycopg://u:p@h/d",
     "postgresql+asyncpg://u:p@h/d"),

    # sslmode is a libpq-only param — asyncpg rejects it, so it must be
    # stripped from the URL. The equivalent ssl kwarg is exposed via
    # Settings.async_connect_args (see the tests below).
    ("postgresql://u:p@h/d?sslmode=require",
     "postgresql+asyncpg://u:p@h/d"),
    ("postgresql+psycopg://u:p@h/d?sslmode=require",
     "postgresql+asyncpg://u:p@h/d"),

    # Neon's real URL shape: both libpq-only params get stripped.
    ("postgresql://u:p@h/d?sslmode=require&channel_binding=require",
     "postgresql+asyncpg://u:p@h/d"),

    # A non-libpq query param survives on the async path.
    ("postgresql://u:p@h/d?application_name=newslens",
     "postgresql+asyncpg://u:p@h/d?application_name=newslens"),

    # Mixed: strip only the libpq ones, keep the rest.
    ("postgresql://u:p@h/d?sslmode=require&application_name=newslens",
     "postgresql+asyncpg://u:p@h/d?application_name=newslens"),

    # ssl=… (asyncpg-native) is NOT stripped — it's asyncpg's own vocab.
    ("postgresql+asyncpg://u:p@h/d?ssl=require",
     "postgresql+asyncpg://u:p@h/d?ssl=require"),
])
def test_to_async_dsn_strips_libpq_params_and_normalizes_dialect(raw, expected):
    from src.config import _to_async_dsn
    assert _to_async_dsn(raw) == expected


# ------ asyncpg SSL kwarg extraction --------------------------------------
@_pt.mark.parametrize("raw, expected", [
    ("postgresql://u:p@h/d", {}),
    ("postgresql://u:p@h/d?application_name=x", {}),
    ("postgresql://u:p@h/d?sslmode=require", {"ssl": "require"}),
    ("postgresql://u:p@h/d?sslmode=verify-full", {"ssl": "verify-full"}),
    ("postgresql://u:p@h/d?sslmode=disable", {"ssl": "disable"}),
    # sslmode + channel_binding: only sslmode maps to ssl; channel_binding
    # is dropped entirely (asyncpg has no equivalent connect kwarg).
    ("postgresql://u:p@h/d?sslmode=require&channel_binding=require",
     {"ssl": "require"}),
    # Unknown sslmode value → skipped (rather than passing garbage to asyncpg).
    ("postgresql://u:p@h/d?sslmode=bogus", {}),
])
def test_async_ssl_kwarg_from_url(raw, expected):
    from src.config import _async_ssl_kwarg
    assert _async_ssl_kwarg(raw) == expected


def test_settings_sync_and_async_properties(monkeypatch):
    """End-to-end: a real Neon-shaped URL is normalized on both sides.

    Sync path keeps sslmode + channel_binding verbatim.
    Async path strips both, and Settings.async_connect_args carries the
    ssl requirement for create_async_engine to pass through."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:p@h/d?sslmode=require&channel_binding=require",
    )
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "x")
    from src.config import get_settings
    get_settings.cache_clear()
    s = get_settings()

    # Sync path: full DSN preserved for psycopg 3.
    assert s.sync_database_url == (
        "postgresql+psycopg://u:p@h/d?sslmode=require&channel_binding=require"
    )
    # Async path: libpq params stripped; asyncpg gets a clean URL.
    assert s.async_database_url == "postgresql+asyncpg://u:p@h/d"
    # And the SSL requirement is carried through connect_args.
    assert s.async_connect_args == {"ssl": "require"}


def test_settings_async_connect_args_empty_without_sslmode(monkeypatch):
    """When there is no sslmode in the DSN, async_connect_args is empty
    and asyncpg applies its own default."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/d")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "x")
    from src.config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    assert s.async_database_url == "postgresql+asyncpg://u:p@h/d"
    assert s.async_connect_args == {}


def test_session_engine_receives_connect_args(monkeypatch):
    """Regression guard: `_engine()` must actually pass the
    `async_connect_args` into `create_async_engine(connect_args=...)`.

    Uses monkeypatch to intercept `create_async_engine`; makes no real
    DB connection. This is the specific check that would have prevented
    the `TypeError: connect() got an unexpected keyword argument 'sslmode'`
    seen at first-query time.
    """
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:p@h/d?sslmode=require&channel_binding=require",
    )
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "x")

    from src.config import get_settings
    get_settings.cache_clear()

    from src.db import session as session_mod
    session_mod._engine.cache_clear()
    session_mod._sessionmaker.cache_clear()

    captured: dict = {}

    def _fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        # Return a sentinel — we never actually connect.
        return object()

    monkeypatch.setattr(session_mod, "create_async_engine",
                        _fake_create_async_engine)

    engine = session_mod._engine()
    assert engine is not None
    # URL must be the sanitised async DSN, no sslmode present anywhere.
    assert captured["url"] == "postgresql+asyncpg://u:p@h/d"
    assert "sslmode" not in captured["url"]
    # And the ssl requirement travels via connect_args.
    assert captured["kwargs"].get("connect_args") == {"ssl": "require"}
    # pool_pre_ping is still on (defensive DB connection health check).
    assert captured["kwargs"].get("pool_pre_ping") is True

    # Cleanup so later tests get a fresh engine cache.
    session_mod._engine.cache_clear()
    session_mod._sessionmaker.cache_clear()
