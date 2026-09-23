"""Dashboard overview endpoint.

One aggregate call powers the home-page KPI row so the dashboard can
render without fanning out to N smaller endpoints. All work is done in
PostgreSQL (no full-table pulls into Python).
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select, text

from src.api.deps import Session
from src.api.schemas import DashboardOverview, LatestIngestionRun
from src.db.models import (
    Article,
    ArticleAnalysis,
    IngestionRun,
    Outlet,
    Story,
)

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=DashboardOverview)
async def overview(session: Session) -> DashboardOverview:
    article_count = await session.scalar(select(func.count()).select_from(Article))
    story_count   = await session.scalar(select(func.count()).select_from(Story))
    outlet_count  = await session.scalar(
        select(func.count()).select_from(Outlet).where(Outlet.active.is_(True))
    )

    # Articles by processing_state — one small aggregate query.
    state_rows = (await session.execute(
        select(Article.processing_state, func.count())
        .group_by(Article.processing_state)
    )).all()
    articles_by_state = {state: n for state, n in state_rows}

    # 24-hour activity.
    articles_last_24h = await session.scalar(text("""
        SELECT COUNT(*) FROM articles
         WHERE published_at >= NOW() - INTERVAL '24 hours'
    """))
    stories_last_24h  = await session.scalar(text("""
        SELECT COUNT(*) FROM stories
         WHERE last_seen_at >= NOW() - INTERVAL '24 hours'
    """))

    # Latest ingestion run.
    latest_ir = await session.scalar(
        select(IngestionRun).order_by(IngestionRun.id.desc()).limit(1)
    )
    latest_payload = None
    if latest_ir is not None:
        latest_payload = LatestIngestionRun(
            id=latest_ir.id,
            started_at=latest_ir.started_at,
            completed_at=latest_ir.completed_at,
            status=latest_ir.status,
            articles_discovered=latest_ir.articles_discovered,
            articles_inserted=latest_ir.articles_inserted,
            articles_failed=latest_ir.articles_failed,
            llm_calls=latest_ir.llm_calls,
        )

    # Framing distribution across analyses.
    dist_rows = (await session.execute(
        select(ArticleAnalysis.framing_label, func.count())
        .where(ArticleAnalysis.framing_label.isnot(None))
        .group_by(ArticleAnalysis.framing_label)
    )).all()
    framing_distribution = {label: n for label, n in dist_rows}

    return DashboardOverview(
        article_count=int(article_count or 0),
        story_count=int(story_count or 0),
        active_outlet_count=int(outlet_count or 0),
        articles_by_state=articles_by_state,
        articles_last_24h=int(articles_last_24h or 0),
        stories_last_24h=int(stories_last_24h or 0),
        latest_ingestion_run=latest_payload,
        framing_distribution=framing_distribution,
    )
