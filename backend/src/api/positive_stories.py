"""Positive Stories endpoint — deterministic ranked feed.

"Positive Stories" describes stories whose CROSS-OUTLET COVERAGE is
predominantly positive/constructive in tone (per-article
``body_sentiment`` aggregated to the story level). It is NOT a claim
that any real-world event is objectively "good news".

Two-phase implementation, mirroring the pattern established by
``bias_distribution`` and ``story_images``:

  1. A single SQL aggregation computes the per-story numeric summary
     (:class:`StorySentimentAggregate`) directly from tables NewsLens
     already has:

         stories.last_seen_at            — freshness
         articles.outlet_id              — distinct-outlet count
         article_analysis.body_sentiment — per-article sentiment

     No LLM, no new table, no new column. The SQL filters out stories
     that have no analyzed articles at all so the second-phase Python
     rule doesn't have to walk useless rows.

  2. :func:`select_positive_stories` (pure Python) applies the
     deterministic qualification + ranking rule.

  3. A follow-up query hydrates the surviving story ids into the shared
     :class:`StorySummary` shape the frontend already consumes for the
     Home feed — same schema, same fields, no new client contract.

Interval binding note: asyncpg is strictly typed. We bind the
freshness window as an ``INTEGER * INTERVAL '1 day'`` parameter, the
same idiom used by ``trends.py``, so the parameter stays a proper
integer bind.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import select, text

from src.analysis.positive_stories import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MIN_ANALYZED_ARTICLES,
    MIN_OUTLETS,
    POSITIVE_ARTICLE_THRESHOLD,
    POSITIVE_FRACTION,
    POSITIVE_MEAN_THRESHOLD,
    RECENT_WINDOW_DAYS,
    StorySentimentAggregate,
    select_positive_stories,
)
from src.analysis.story_images import (
    ArticleImageCandidate,
    hero_image_from_selection,
    select_story_images,
)
from src.api.deps import Session
from src.api.schemas import StorySummary
from src.db.models import Article, Outlet, Story, StoryComparison

router = APIRouter(tags=["positive-stories"])


@router.get("/positive-stories", response_model=list[StorySummary])
async def positive_stories(
    session: Session,
    limit: int = Query(
        DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=(
            "Maximum number of positive stories to return "
            f"(1..{MAX_LIMIT}, default {DEFAULT_LIMIT})."
        ),
    ),
) -> list[StorySummary]:
    """Stories whose coverage across outlets has been predominantly
    positive over the last :data:`RECENT_WINDOW_DAYS` days.

    Deterministic — same inputs produce the same output, always. The
    exact rule (thresholds, ordering, disqualification reasons) lives
    in :mod:`src.analysis.positive_stories`.
    """

    # ------------------------------------------------------------------
    # 1. Per-story sentiment aggregate (single SQL GROUP BY).
    #
    #    Filtering done in SQL:
    #      * freshness (stories.last_seen_at within window)
    #      * body_sentiment IS NOT NULL (only analyzed articles count)
    #
    #    All other rules are applied in Python by qualifies() so the
    #    logic is unit-testable without a database.
    # ------------------------------------------------------------------
    agg_rows = (await session.execute(text(f"""
        SELECT s.id                                           AS story_id,
               s.last_seen_at                                 AS last_seen_at,
               COUNT(DISTINCT a.outlet_id)                    AS distinct_outlets,
               COUNT(*)                                       AS analyzed_articles,
               AVG(aa.body_sentiment)::float                  AS mean_body_sentiment,
               SUM(
                 CASE WHEN aa.body_sentiment >= :pos_article THEN 1 ELSE 0 END
               )::int                                         AS positive_articles
          FROM stories s
          JOIN articles a          ON a.story_id  = s.id
          JOIN article_analysis aa ON aa.article_id = a.id
         WHERE s.last_seen_at >= NOW() - (:days * INTERVAL '1 day')
           AND aa.body_sentiment IS NOT NULL
         GROUP BY s.id, s.last_seen_at
    """), {
        "pos_article": POSITIVE_ARTICLE_THRESHOLD,
        "days": RECENT_WINDOW_DAYS,
    })).all()

    aggregates = [
        StorySentimentAggregate(
            story_id=r.story_id,
            last_seen_at=r.last_seen_at,
            distinct_outlets=int(r.distinct_outlets or 0),
            analyzed_articles=int(r.analyzed_articles or 0),
            positive_articles=int(r.positive_articles or 0),
            mean_body_sentiment=(float(r.mean_body_sentiment)
                                 if r.mean_body_sentiment is not None
                                 else None),
        )
        for r in agg_rows
    ]

    # ------------------------------------------------------------------
    # 2. Apply the deterministic qualification + ranking rule.
    # ------------------------------------------------------------------
    picked = select_positive_stories(
        aggregates,
        now=datetime.now(timezone.utc),
        limit=limit,
        window_days=RECENT_WINDOW_DAYS,
        min_outlets=MIN_OUTLETS,
        min_analyzed=MIN_ANALYZED_ARTICLES,
        positive_mean=POSITIVE_MEAN_THRESHOLD,
        positive_article=POSITIVE_ARTICLE_THRESHOLD,
        positive_fraction=POSITIVE_FRACTION,
    )
    if not picked:
        return []

    picked_ids = [a.story_id for a in picked]
    rank_by_id: dict[int, int] = {sid: i for i, sid in enumerate(picked_ids)}

    # ------------------------------------------------------------------
    # 3. Hydrate the surviving story ids into StorySummary shape.
    #    Same pattern as list_stories: story rows, outlet slugs, and
    #    image candidates in a bounded number of queries.
    # ------------------------------------------------------------------
    rows_q = (
        select(Story, StoryComparison.framing_spread)
        .outerjoin(StoryComparison, StoryComparison.story_id == Story.id)
        .where(Story.id.in_(picked_ids))
    )
    rows = (await session.execute(rows_q)).all()

    # Outlet slugs per story, single query — same anti-N+1 shape as
    # list_stories.
    outlet_rows = (await session.execute(
        select(Article.story_id, Outlet.slug)
        .join(Outlet, Outlet.id == Article.outlet_id)
        .where(Article.story_id.in_(picked_ids))
        .distinct()
    )).all()
    outlets_by_story: dict[int, list[str]] = {}
    for sid, slug in outlet_rows:
        outlets_by_story.setdefault(sid, []).append(slug)

    # Image candidates for hero_image_url.
    img_rows = (await session.execute(
        select(
            Article.story_id, Article.id, Article.image_url,
            Article.published_at, Outlet.slug, Outlet.name,
        )
        .join(Outlet, Outlet.id == Article.outlet_id)
        .where(Article.story_id.in_(picked_ids))
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
        picked_imgs = select_story_images(
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
            hero_image_url=hero_image_from_selection(picked_imgs),
        ))

    # Preserve the deterministic rank produced by select_positive_stories.
    # The `IN (...)` query above doesn't guarantee row order.
    items.sort(key=lambda x: rank_by_id.get(x.id, 10**9))
    return items
