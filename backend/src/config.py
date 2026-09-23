"""Runtime configuration.

Loaded once at process start via Pydantic Settings. All secrets come from
environment variables; nothing is committed. See `.env.example` for the
required keys and the architecture doc §14 for where each one is set.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# libpq-only DSN query parameters. These are understood by psycopg (which
# wraps libpq natively) but NOT by asyncpg, which will raise
#     TypeError: connect() got an unexpected keyword argument 'sslmode'
# when SQLAlchemy passes them through. `_to_async_dsn` strips them and
# `_async_ssl_kwarg` translates the SSL requirement into asyncpg's own
# vocabulary so the equivalent behaviour is preserved.
# ---------------------------------------------------------------------------
_LIBPQ_ONLY_PARAMS: frozenset[str] = frozenset({"sslmode", "channel_binding"})

# sslmode → asyncpg ssl mapping. asyncpg uses the same vocabulary as
# libpq (disable/allow/prefer/require/verify-ca/verify-full) but under
# the connect kwarg name `ssl` instead of `sslmode`.
_ASYNCPG_SSL_MODES: frozenset[str] = frozenset({
    "disable", "allow", "prefer", "require", "verify-ca", "verify-full",
})


class Settings(BaseSettings):
    """Backend settings.

    Fields without a default are required; the process fails to start if
    they are missing, which is the intended behavior for a misconfigured
    deploy.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database ---------------------------------------------------------
    database_url: str = Field(..., description="Neon Postgres URL (asyncpg).")

    # --- LLM --------------------------------------------------------------
    groq_api_key: str = Field(..., description="Groq API key for enrich/compare calls.")
    llm_model: str = Field(..., description="Groq model string; recorded on analysis_runs rows.")

    # --- API --------------------------------------------------------------
    cors_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated origins for CORS.",
    )

    # --- Kill switch ------------------------------------------------------
    ingestion_enabled: bool = Field(default=True, description="Master ingestion kill switch.")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        """DATABASE_URL rewritten to force the sync psycopg 3 driver.

        Alembic, the ingestion orchestrator, and the seed script all use
        SQLAlchemy sync engines. If DATABASE_URL is bare `postgresql://`
        (Neon's default connection string), SQLAlchemy defaults to
        `postgresql+psycopg2` and crashes with ModuleNotFoundError —
        psycopg2 is not in our approved stack. This property normalizes
        every accepted DSN shape to the `+psycopg` driver.

        Query params (sslmode, channel_binding, …) are preserved verbatim
        because psycopg 3 wraps libpq and understands them all natively.
        """
        return _to_sync_dsn(self.database_url)

    @property
    def async_database_url(self) -> str:
        """DATABASE_URL rewritten to force the async asyncpg driver.

        Used by ``src.db.session`` for FastAPI request handlers. Same
        rationale as ``sync_database_url``: a bare ``postgresql://`` URL
        would route to the sync psycopg2 dialect (which can't do async
        at all).

        libpq-only query parameters (``sslmode``, ``channel_binding``)
        are STRIPPED here because asyncpg does not accept them at
        connect time. The SSL requirement is preserved via
        :pyattr:`async_connect_args`, which the engine factory must pass
        into ``create_async_engine(..., connect_args=...)``.
        """
        return _to_async_dsn(self.database_url)

    @property
    def async_connect_args(self) -> dict[str, str]:
        """Extra kwargs to hand to ``create_async_engine(connect_args=...)``.

        Encodes the SSL requirement that was stripped from
        :pyattr:`async_database_url`. Empty dict when the URL carries no
        SSL directive.
        """
        return _async_ssl_kwarg(self.database_url)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------
def _split_url_query(url: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (url_without_query, [(k, v), ...]) preserving order.

    Uses a list of tuples so duplicate keys survive round-trip.
    """
    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)
    stripped = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, "", parts.fragment)
    )
    return stripped, params


def _rebuild_url(base: str, params: list[tuple[str, str]]) -> str:
    """Reattach ordered query params to a base URL; return base if empty."""
    if not params:
        return base
    parts = urlsplit(base)
    query = urlencode(params)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, query, parts.fragment)
    )


def _to_sync_dsn(url: str) -> str:
    """Normalize any accepted DSN shape to ``postgresql+psycopg://``.

    Query params are preserved verbatim (psycopg 3 speaks libpq natively).
    """
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg", 1)
    if "+psycopg" in url:
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url  # some other custom dialect — leave alone


def _to_async_dsn(url: str) -> str:
    """Normalize any accepted DSN shape to ``postgresql+asyncpg://``.

    IMPORTANT: strips libpq-only query params (``sslmode``,
    ``channel_binding``) that asyncpg rejects. The equivalent SSL
    setting is available via :func:`_async_ssl_kwarg` for callers that
    need to pass it through ``create_async_engine(connect_args=...)``.
    """
    # Step 1 — rewrite the dialect prefix.
    if "+psycopg" in url:
        url = url.replace("+psycopg", "+asyncpg", 1)
    elif url.startswith("postgresql+asyncpg://"):
        pass  # already correct
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    else:
        return url  # some other custom dialect — leave alone

    # Step 2 — strip libpq-only query params so asyncpg's connect()
    # never sees keywords it can't accept.
    base, params = _split_url_query(url)
    filtered = [(k, v) for k, v in params if k.lower() not in _LIBPQ_ONLY_PARAMS]
    return _rebuild_url(base, filtered)


def _async_ssl_kwarg(url: str) -> dict[str, str]:
    """Translate ``sslmode=<value>`` from a DSN into ``{"ssl": "<value>"}``.

    asyncpg's ``ssl`` connect kwarg accepts the same vocabulary as
    libpq's ``sslmode`` (disable/allow/prefer/require/verify-ca/
    verify-full), so the value carries over 1-for-1.

    Returns an empty dict when the URL has no ``sslmode`` param or
    when the value is not one asyncpg recognises. Empty means "let
    asyncpg apply its own default" (which is 'prefer' — same as libpq).
    """
    _, params = _split_url_query(url)
    sslmode = ""
    for k, v in params:
        if k.lower() == "sslmode":
            sslmode = (v or "").strip().lower()
            break
    if sslmode and sslmode in _ASYNCPG_SSL_MODES:
        return {"ssl": sslmode}
    return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()  # type: ignore[call-arg]
