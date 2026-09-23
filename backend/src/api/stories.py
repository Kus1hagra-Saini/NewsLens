"""Stories API — listing (paginated) + detail (with articles + comparison).

Uses SQLAlchemy async sessions and existing indexes:
  * ``ix_stories_last_seen_at_desc`` — ORDER BY last_seen_at DESC
  * ``ix_articles_story_id``          — the article-by-story join
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.api.deps import Pagination, Session
from src.api.schemas import (
    ArticleAnalysisPayload,
    ArticleInStory,
    OutletSummary,
    PaginatedStories,
    StoryComparisonPayload,
    StoryDetail,
    StorySummary,
)
from src.db.models import (
    Article,
    ArticleAnalysis,
    Outlet,
    Story,
    StoryComparison,
)

router = APIRouter(prefix="/stories", tags=["stories"])


@router.get("", response_model=PaginatedStories)
async def list_stories(session: Session, pg: Pagination) -> PaginatedStories:
    # Total count in a single scalar query.
    total = await session.scalar(select(func.count()).select_from(Story))

    # Base story rows, most-recently-seen first.
    rows_q = (
        select(Story, StoryComparison.framing_spread)
        .outerjoin(StoryComparison, StoryComparison.story_id == Story.id)
        .order_by(Story.last_seen_at.desc(), Story.id.desc())
        .limit(pg["limit"])
        .offset(pg["offset"])
    )
    rows = (await session.execute(rows_q)).all()

    if not rows:
        return PaginatedStories(items=[], page=pg["page"], limit=pg["limit"],
                                 total=total or 0, has_more=False)

    story_ids = [r.Story.id for r in rows]

    # Outlet slugs per story, single query — avoids N+1.
    outlet_rows = (await session.execute(
        select(Article.story_id, Outlet.slug)
        .join(Outlet, Outlet.id == Article.outlet_id)
        .where(Article.story_id.in_(story_ids))
        .distinct()
    )).all()
    outlets_by_story: dict[int, list[str]] = {}
    for sid, slug in outlet_rows:
        outlets_by_story.setdefault(sid, []).append(slug)

    items: list[StorySummary] = []
    for r in rows:
        s: Story = r.Story
        items.append(StorySummary(
            id=s.id,
            title=s.title,
            topic=s.topic,
            first_seen_at=s.first_seen_at,
            last_seen_at=s.last_seen_at,
            article_count=s.article_count,
            summary=s.summary,
            outlet_slugs=sorted(outlets_by_story.get(s.id, [])),
            framing_spread=(float(r.framing_spread)
                            if r.framing_spread is not None else None),
        ))

    return PaginatedStories(
        items=items,
        page=pg["page"],
        limit=pg["limit"],
        total=total or 0,
        has_more=(pg["offset"] + len(items)) < (total or 0),
    )


@router.get("/{story_id}", response_model=StoryDetail)
async def get_story(story_id: int, session: Session) -> StoryDetail:
    story = await session.scalar(
        select(Story).where(Story.id == story_id)
    )
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"story {story_id} not found",
        )

    # Articles + their outlet + optional analysis. Eager-loaded to prevent
    # N+1 when we hydrate ArticleAnalysisPayload per article.
    art_rows = (await session.execute(
        select(Article, Outlet, ArticleAnalysis)
        .join(Outlet, Outlet.id == Article.outlet_id)
        .outerjoin(ArticleAnalysis, ArticleAnalysis.article_id == Article.id)
        .where(Article.story_id == story_id)
        .order_by(Article.published_at.asc(), Article.id.asc())
    )).all()

    articles: list[ArticleInStory] = []
    outlet_slugs: set[str] = set()
    for article, outlet, aa in art_rows:
        outlet_slugs.add(outlet.slug)
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
        articles.append(ArticleInStory(
            id=article.id,
            outlet=OutletSummary.model_validate(outlet),
            url=article.url,
            headline=article.headline,
            author=article.author,
            published_at=article.published_at,
            processing_state=article.processing_state,
            analysis=analysis_payload,
        ))

    # Comparison (nullable).
    sc = await session.scalar(
        select(StoryComparison).where(StoryComparison.story_id == story_id)
    )
    comparison_payload: StoryComparisonPayload | None = None
    if sc is not None:
        comparison_payload = StoryComparisonPayload(
            differences=sc.differences,
            framing_spread=(float(sc.framing_spread)
                             if sc.framing_spread is not None else None),
            coverage_matrix=sc.coverage_matrix,
            not_present_here=sc.not_present_here,
            generated_at=sc.generated_at,
        )

    return StoryDetail(
        id=story.id,
        title=story.title,
        topic=story.topic,
        first_seen_at=story.first_seen_at,
        last_seen_at=story.last_seen_at,
        article_count=story.article_count,
        summary=story.summary,
        outlet_slugs=sorted(outlet_slugs),
        framing_spread=(comparison_payload.framing_spread
                        if comparison_payload else None),
        articles=articles,
        comparison=comparison_payload,
    )
