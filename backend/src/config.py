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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()  # type: ignore[call-arg]
