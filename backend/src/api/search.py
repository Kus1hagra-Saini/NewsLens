"""Full-text search over articles using the existing generated ``fts``
TSVECTOR column and the GIN index on it (arch §9).

Uses ``plainto_tsquery('english', :q)`` — the same analyzer the
``fts`` column is generated with — so query and stored vector always
speak the same lexemes.

``ts_headline`` produces a short highlighted snippet for each hit.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text

from src.api.deps import Pagination, Session
from src.api.schemas import PaginatedSearch, SearchHit

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=PaginatedSearch)
async def search_articles(
    session: Session,
    pg: Pagination,
    q: str = Query(..., min_length=2, max_length=200, description="Search query"),
) -> PaginatedSearch:
    q = q.strip()
    if not q:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="q must be non-empty",
        )

    # Total count of matches (bounded by index scan, cheap enough).
    total = await session.scalar(text("""
        SELECT COUNT(*) FROM articles
         WHERE fts @@ plainto_tsquery('english', :q)
    """), {"q": q})

    rows = (await session.execute(text("""
        SELECT a.id            AS article_id,
               o.slug          AS outlet_slug,
               a.headline      AS headline,
               a.url           AS url,
               a.published_at  AS published_at,
               ts_rank(a.fts, plainto_tsquery('english', :q)) AS rank,
               ts_headline('english',
                           COALESCE(a.full_text, a.headline),
                           plainto_tsquery('english', :q),
                           'MaxWords=30,MinWords=10,ShortWord=3,'
                           'HighlightAll=false,MaxFragments=1'
               ) AS snippet
          FROM articles a
          JOIN outlets  o ON o.id = a.outlet_id
         WHERE a.fts @@ plainto_tsquery('english', :q)
         ORDER BY rank DESC, a.published_at DESC
         LIMIT :limit OFFSET :offset
    """), {"q": q, "limit": pg["limit"], "offset": pg["offset"]})).all()

    items = [
        SearchHit(
            article_id=r.article_id,
            outlet_slug=r.outlet_slug,
            headline=r.headline,
            url=r.url,
            published_at=r.published_at,
            rank=float(r.rank),
            snippet=r.snippet,
        )
        for r in rows
    ]

    total_i = int(total or 0)
    return PaginatedSearch(
        query=q,
        items=items,
        page=pg["page"],
        limit=pg["limit"],
        total=total_i,
        has_more=(pg["offset"] + len(items)) < total_i,
    )
