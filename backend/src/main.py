"""FastAPI entrypoint.

Week 1 scaffold: only `/health` is wired. API routers under `src.api.*` are
placeholders that will be included in Week 3 as they come online.
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

    # Routers wired in later weeks:
    #   from src.api import stories, outlets, trends, search, export, eval as eval_api
    #   app.include_router(stories.router)
    #   ...

    return app


app = create_app()
