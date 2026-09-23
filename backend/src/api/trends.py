"""Trends endpoint — time-series charts for the dashboard.

Aggregations run in PostgreSQL over a bounded time window (default 7
days, capped at 90).

Interval binding note: asyncpg is strictly typed and rejects patterns
that force an integer parameter to text via string concatenation
(``expected str, got int``). We instead multiply the integer parameter
by a literal one-day interval:

    NOW() - (:days * INTERVAL '1 day')

The parameter stays a proper integer bind — no string interpolation
into SQL.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import text

from src.api.deps import Session
from src.api.schemas import FramingBucket, TimeSeriesPoint, TrendsResponse

router = APIRouter(tags=["trends"])


@router.get("/trends", response_model=TrendsResponse)
async def trends(
    session: Session,
    window: int = Query(7, ge=1, le=90,
                        description="Window size in days (1..90)"),
) -> TrendsResponse:
    """Time-series of articles/day, stories/day and framing distribution
    over the last ``window`` days."""

    articles_rows = (await session.execute(text("""
        SELECT to_char(date_trunc('day', published_at), 'YYYY-MM-DD') AS d,
               COUNT(*) AS n
          FROM articles
         WHERE published_at >= NOW() - (:days * INTERVAL '1 day')
         GROUP BY d ORDER BY d
    """), {"days": window})).all()

    stories_rows = (await session.execute(text("""
        SELECT to_char(date_trunc('day', last_seen_at), 'YYYY-MM-DD') AS d,
               COUNT(*) AS n
          FROM stories
         WHERE last_seen_at >= NOW() - (:days * INTERVAL '1 day')
         GROUP BY d ORDER BY d
    """), {"days": window})).all()

    framing_rows = (await session.execute(text("""
        SELECT COALESCE(aa.framing_label, 'unlabeled') AS label,
               COUNT(*) AS n
          FROM article_analysis aa
          JOIN articles a ON a.id = aa.article_id
         WHERE a.published_at >= NOW() - (:days * INTERVAL '1 day')
         GROUP BY label
         ORDER BY label
    """), {"days": window})).all()

    return TrendsResponse(
        window_days=window,
        articles_per_day=[TimeSeriesPoint(date=r.d, count=int(r.n))
                          for r in articles_rows],
        stories_per_day=[TimeSeriesPoint(date=r.d, count=int(r.n))
                         for r in stories_rows],
        framing_distribution=[FramingBucket(label=r.label, count=int(r.n))
                              for r in framing_rows],
    )
