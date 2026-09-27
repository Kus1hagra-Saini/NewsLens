"""Stories API — listing (paginated) + detail (with articles + comparison).

Uses SQLAlchemy async sessions and existing indexes:
  * ``ix_stories_last_seen_at_desc`` — ORDER BY last_seen_at DESC
  * ``ix_articles_story_id``          — the article-by-story join

Home freshness note
-------------------
The Home page reuses this listing via the shared ``useStories`` hook and
passes ``?fresh=true``. When that flag is set, the query gains a single
``WHERE Story.last_seen_at >= NOW() − home_freshness_hours`` clause
(configurable via ``HOME_FRESHNESS_HOURS``, default 72). The Stories
page keeps calling this endpoint WITHOUT the flag, so the historical
archive stays intact. Story Detail (`/stories/{id}`) also stays
accessible — no freshness filter is applied there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.analysis.bias_distribution import (
    OutletInStory,
    OutletRatingRow,
    compute_bias_distribution,
)
from src.analysis.story_images import (
    ArticleImageCandidate,
    hero_image_from_selection,
    select_story_images,
)
from src.api.deps import Pagination, Session
from src.api.schemas import (
    ArticleAnalysisPayload,
    ArticleInStory,
    BiasDistribution,
    BiasDistributionSource,
    OutletSummary,
    PaginatedStories,
    StoryComparisonPayload,
    StoryDetail,
    StoryImage,
    StorySummary,
)
from src.config import get_settings
from src.db.models import (
    Article,
    ArticleAnalysis,
    Outlet,
    OutletBiasRating,
    Story,
    StoryComparison,
)

router = APIRouter(prefix="/stories", tags=["stories"])


def _freshness_cutoff(hours: int) -> datetime:
    """Cutoff timestamp for the Home freshness window.

    Computed in Python rather than as a SQL ``INTERVAL`` for two reasons:
      1. It sidesteps asyncpg's strict typing around integer→interval
         casts (see the note in ``trends.py``).
      2. It keeps the query engine-agnostic; the tests can construct a
         Story with a known ``last_seen_at`` and reason about
         eligibility without also matching Postgres' interval maths.

    Sub-second skew between the API process's clock and the DB's clock
    is meaningless for a 72-hour bucket. ``timezone.utc`` is used
    explicitly because ``stories.last_seen_at`` is a
    ``DateTime(timezone=True)`` column and a naive datetime would
    trigger a comparison error under SQLAlchemy 2.x.
    """
    return datetime.now(timezone.utc) - timedelta(hours=hours)


@router.get("", response_model=PaginatedStories)
async def list_stories(
    session: Session,
    pg: Pagination,
    fresh: bool = Query(
        False,
        description=(
            "When true, restrict the result to stories whose "
            "last_seen_at falls within the configured Home freshness "
            "window (HOME_FRESHNESS_HOURS, default 72h). Used by the "
            "Home page; the general Stories page omits it so the "
            "historical archive stays intact."
        ),
    ),
) -> PaginatedStories:
    # Build the freshness WHERE clause once and share it between the
    # COUNT and the SELECT so the reported ``total`` matches what the
    # page can actually paginate through.
    where_clauses: list = []
    if fresh:
        cutoff = _freshness_cutoff(get_settings().home_freshness_hours)
        # Inclusive on the boundary — a story last seen exactly at the
        # cutoff still qualifies (matches the project's existing
        # trends.py + positive_stories.py style).
        where_clauses.append(Story.last_seen_at >= cutoff)

    # Total count in a single scalar query, respecting the same filter
    # the row query uses so pagination math stays honest.
    count_q = select(func.count()).select_from(Story)
    if where_clauses:
        count_q = count_q.where(*where_clauses)
    total = await session.scalar(count_q)

    # Base story rows, most-recently-seen first. Ordering is UNCHANGED
    # by the freshness rule — the filter only constrains the candidate
    # set; it does not touch ranking (spec Step 5).
    rows_q = (
        select(Story, StoryComparison.framing_spread)
        .outerjoin(StoryComparison, StoryComparison.story_id == Story.id)
        .order_by(Story.last_seen_at.desc(), Story.id.desc())
        .limit(pg["limit"])
        .offset(pg["offset"])
    )
    if where_clauses:
        rows_q = rows_q.where(*where_clauses)
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

    # Per-story image candidates for hero_image_url. One row per
    # (story, article) that has a non-null image_url. The pure
    # selector below handles dedupe + outlet diversity + count-rule.
    img_rows = (await session.execute(
        select(
            Article.story_id, Article.id, Article.image_url,
            Article.published_at, Outlet.slug, Outlet.name,
        )
        .join(Outlet, Outlet.id == Article.outlet_id)
        .where(Article.story_id.in_(story_ids))
        .where(Article.image_url.is_not(None))
    )).all()
    candidates_by_story: dict[int, list[ArticleImageCandidate]] = {}
    for sid, aid, iurl, pub, oslug, oname in img_rows:
        candidates_by_story.setdefault(sid, []).append(
            ArticleImageCandidate(
                article_id=aid,
                outlet_slug=oslug,
                outlet_name=oname,
                image_url=iurl,
                published_at_ts=pub.timestamp() if pub else 0.0,
            )
        )

    items: list[StorySummary] = []
    for r in rows:
        s: Story = r.Story
        # Only need the hero for the list view — the detail endpoint
        # returns the full selected image list.
        picked = select_story_images(
            candidates=candidates_by_story.get(s.id, []),
            total_article_count=s.article_count or 0,
        )
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
            hero_image_url=hero_image_from_selection(picked),
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
    # Deduplicate outlets while preserving id/name/slug for the bias
    # distribution — an outlet that published multiple articles must
    # be counted once.
    distinct_outlets: dict[int, OutletInStory] = {}
    for article, outlet, aa in art_rows:
        outlet_slugs.add(outlet.slug)
        distinct_outlets.setdefault(
            outlet.id,
            OutletInStory(id=outlet.id, slug=outlet.slug, name=outlet.name),
        )
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
            image_url=article.image_url,
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

    # ------------------------------------------------------------------
    # Bias distribution — publication-level, NOT article-level.
    # Read every rating row for the outlets covering this story in one
    # query, hand it to the pure `compute_bias_distribution` helper, and
    # serialise the result into the API schema.
    # ------------------------------------------------------------------
    bias_distribution_payload: BiasDistribution | None = None
    if distinct_outlets:
        rating_rows = (await session.execute(
            select(OutletBiasRating, Outlet)
            .join(Outlet, Outlet.id == OutletBiasRating.outlet_id)
            .where(OutletBiasRating.outlet_id.in_(list(distinct_outlets.keys())))
        )).all()

        rating_records = [
            OutletRatingRow(
                outlet_id=r.outlet_id,
                outlet_slug=o.slug,
                outlet_name=o.name,
                source=r.source,
                original_label=r.original_label,
                normalized_category=r.normalized_category,
                rating_url=r.rating_url,
                rated_at=r.rated_at,
            )
            for r, o in rating_rows
        ]
        dist = compute_bias_distribution(
            outlets=distinct_outlets.values(),
            ratings=rating_records,
        )
        bias_distribution_payload = BiasDistribution(
            eligible=dist.eligible,
            reason=dist.reason,
            total_outlet_count=dist.total_outlet_count,
            rated_outlet_count=dist.rated_outlet_count,
            unrated_outlet_count=dist.unrated_outlet_count,
            unrated_outlet_slugs=list(dist.unrated_outlet_slugs),
            distribution={k: float(v) for k, v in dist.distribution.items()},
            counts={k: int(v) for k, v in dist.counts.items()},
            sources=[
                BiasDistributionSource(
                    outlet_id=s.outlet_id,
                    outlet_slug=s.outlet_slug,
                    outlet_name=s.outlet_name,
                    original_rating=s.original_rating,
                    normalized_category=s.normalized_category,
                    rating_source=s.rating_source,
                    rating_url=s.rating_url,
                    rated_at=s.rated_at,
                )
                for s in dist.sources
            ],
        )

    # ------------------------------------------------------------------
    # Story-level image selection — hero + up to N supporting images
    # per the deterministic count rule (see analysis.story_images).
    # ------------------------------------------------------------------
    img_candidates = [
        ArticleImageCandidate(
            article_id=a.id,
            outlet_slug=a.outlet.slug,
            outlet_name=a.outlet.name,
            image_url=a.image_url,
            published_at_ts=a.published_at.timestamp() if a.published_at else 0.0,
        )
        for a in articles
        if a.image_url
    ]
    picked_images = select_story_images(
        candidates=img_candidates,
        total_article_count=story.article_count or len(articles),
    )
    story_images_payload = [
        StoryImage(
            url=p.url,
            article_id=p.article_id,
            outlet_slug=p.outlet_slug,
            outlet_name=p.outlet_name,
        )
        for p in picked_images
    ]
    hero_url = hero_image_from_selection(picked_images)

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
        hero_image_url=hero_url,
        articles=articles,
        comparison=comparison_payload,
        bias_distribution=bias_distribution_payload,
        story_images=story_images_payload,
    )
