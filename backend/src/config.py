"""Runtime configuration.

Loaded once at process start via Pydantic Settings. All secrets come from
environment variables; nothing is committed. See `.env.example` for the
required keys and the architecture doc §14 for where each one is set.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        """
        return _to_sync_dsn(self.database_url)

    @property
    def async_database_url(self) -> str:
        """DATABASE_URL rewritten to force the async asyncpg driver.

        Used by src.db.session for FastAPI request handlers. Same
        rationale as sync_database_url: a bare `postgresql://` URL would
        route to the sync psycopg2 dialect (which can't do async at all).
        """
        return _to_async_dsn(self.database_url)


def _to_sync_dsn(url: str) -> str:
    """Normalize any accepted DSN shape to `postgresql+psycopg://`."""
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
    """Normalize any accepted DSN shape to `postgresql+asyncpg://`."""
    if "+psycopg" in url:
        return url.replace("+psycopg", "+asyncpg", 1)
    if "+asyncpg" in url:
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()  # type: ignore[call-arg]
