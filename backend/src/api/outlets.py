"""Outlets API — list, single, 30-day stats (uses outlet_30d_stats view)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, text

from src.api.deps import Session
from src.api.schemas import OutletDetail, OutletStats, OutletSummary
from src.db.models import Outlet

router = APIRouter(prefix="/outlets", tags=["outlets"])


@router.get("", response_model=list[OutletSummary])
async def list_outlets(session: Session) -> list[OutletSummary]:
    rows = (await session.scalars(
        select(Outlet).where(Outlet.active.is_(True)).order_by(Outlet.name)
    )).all()
    return [OutletSummary.model_validate(o) for o in rows]


@router.get("/{slug}", response_model=OutletDetail)
async def get_outlet(slug: str, session: Session) -> OutletDetail:
    outlet = await session.scalar(select(Outlet).where(Outlet.slug == slug))
    if outlet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"outlet {slug!r} not found",
        )
    return OutletDetail.model_validate(outlet)


@router.get("/{slug}/stats", response_model=OutletStats)
async def outlet_stats(slug: str, session: Session) -> OutletStats:
    """30-day rolling stats. Reads the ``outlet_30d_stats`` materialized
    view (arch §9) which is refreshed daily by a GitHub Actions job.
    Falls back to zero-populated stats if the outlet exists but has no
    articles in the last 30 days (so the view has no row for it)."""
    outlet = await session.scalar(select(Outlet).where(Outlet.slug == slug))
    if outlet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"outlet {slug!r} not found",
        )

    row = (await session.execute(text("""
        SELECT article_count,
               avg_framing,
               avg_sentiment,
               top_themes
          FROM outlet_30d_stats
         WHERE outlet_id = :oid
    """), {"oid": outlet.id})).first()

    if row is None:
        return OutletStats(
            outlet_id=outlet.id,
            slug=outlet.slug,
            name=outlet.name,
            article_count=0,
            avg_framing=None,
            avg_sentiment=None,
            top_themes=None,
        )

    return OutletStats(
        outlet_id=outlet.id,
        slug=outlet.slug,
        name=outlet.name,
        article_count=row.article_count or 0,
        avg_framing=(float(row.avg_framing)
                     if row.avg_framing is not None else None),
        avg_sentiment=(float(row.avg_sentiment)
                        if row.avg_sentiment is not None else None),
        top_themes=row.top_themes,
    )
