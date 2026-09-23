"""Article detail endpoint. Does NOT return full_text by default —
long article bodies are unnecessary for the dashboard views and full_text
should only travel when explicitly requested (deferred).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from src.api.deps import Session
from src.api.schemas import (
    ArticleAnalysisPayload,
    ArticleDetail,
    OutletSummary,
)
from src.db.models import Article, ArticleAnalysis, Outlet

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("/{article_id}", response_model=ArticleDetail)
async def get_article(article_id: int, session: Session) -> ArticleDetail:
    row = (await session.execute(
        select(Article, Outlet, ArticleAnalysis)
        .join(Outlet, Outlet.id == Article.outlet_id)
        .outerjoin(ArticleAnalysis, ArticleAnalysis.article_id == Article.id)
        .where(Article.id == article_id)
    )).first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"article {article_id} not found",
        )

    article, outlet, aa = row

    analysis_payload: ArticleAnalysisPayload | None = None
    if aa is not None:
        analysis_payload = ArticleAnalysisPayload(
            framing_score=(float(aa.framing_score)
                            if aa.framing_score is not None else None),
            framing_label=aa.framing_label,
            framing_confidence=(float(aa.framing_confidence)
                                 if aa.framing_confidence is not None else None),
            headline_sentiment=(float(aa.headline_sentiment)
                                 if aa.headline_sentiment is not None else None),
            body_sentiment=(float(aa.body_sentiment)
                             if aa.body_sentiment is not None else None),
            key_themes=list(aa.key_themes or []),
            entities=aa.entities or {},
            quoted_sources=list(aa.quoted_sources or []),
            source_distribution=aa.source_distribution,
            evidence_snippets=list(aa.evidence_snippets or []),
            analyzed_at=aa.analyzed_at,
        )

    return ArticleDetail(
        id=article.id,
        outlet=OutletSummary.model_validate(outlet),
        url=article.url,
        headline=article.headline,
        author=article.author,
        published_at=article.published_at,
        processing_state=article.processing_state,
        analysis=analysis_payload,
        story_id=article.story_id,
        full_text_available=(article.full_text is not None
                              and len(article.full_text) > 0),
    )
