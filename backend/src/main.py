"""FastAPI entrypoint.

Wires ``/health`` plus the API routers under ``src.api.*``.

Kept intentionally small — router modules own their own path prefixes
and response models; this file only assembles them.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(title="NewsLens API", version="0.1.0")

    cfg = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Import routers lazily so pure /health tests don't need the DB
    # session module imported at app startup (they still do end up
    # importing it via the routers below, but the import graph stays
    # explicit and grep-able).
    from src.api import articles, outlets, overview, search, stories, trends

    app.include_router(overview.router)
    app.include_router(stories.router)
    app.include_router(articles.router)
    app.include_router(outlets.router)
    app.include_router(search.router)
    app.include_router(trends.router)

    return app


app = create_app()
