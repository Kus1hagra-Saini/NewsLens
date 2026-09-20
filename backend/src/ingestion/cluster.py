"""Story clustering via pgvector cosine nearest-neighbor.

Architecture §10 step 6:
    'For each embedded article, find nearest neighbors within the last
    3 days via pgvector cosine similarity. If max similarity > 0.75,
    assign to that story. Else create a new story.'

Implementation notes:
  - We compare against ALREADY-clustered articles (state in ('clustered',
    'analyzed', 'complete') OR any article that already has a story_id).
    A batch of newly-embedded articles is processed one at a time so a
    later article in the same batch CAN attach to a story created by an
    earlier one.
  - pgvector's cosine distance operator is `<=>`; cosine similarity is
    `1 - (a <=> b)`.
  - When no neighbor above the threshold is found, we create a new
    stories row with title = article.headline (the first article in a
    cluster names it — an LLM can later refine `summary`).
  - stories.article_count and stories.last_seen_at are maintained by this
    module so downstream reads don't need extra JOINs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import bindparam, select, text, update
from sqlalchemy.orm import Session

from src.db.models import Article, Story

log = logging.getLogger(__name__)

# Documented threshold; §10 step 6.
SIMILARITY_THRESHOLD = 0.75
# Documented look-back window; §10 step 6.
LOOKBACK_DAYS = 3


@dataclass
class ClusterOutcome:
    articles_clustered: int
    new_stories: int
    attached_to_existing: int


def cluster_articles(
    session: Session,
    *,
    batch_limit: int = 100,
    threshold: float = SIMILARITY_THRESHOLD,
    lookback_days: int = LOOKBACK_DAYS,
) -> ClusterOutcome:
    """Advance up to `batch_limit` articles from embedded → clustered.

    Attaches each article to the most-similar recent story if its
    similarity is above `threshold`; otherwise creates a new story.
    Returns counts for logging + ingestion_runs bookkeeping.
    """
    q = (
        select(Article)
        .where(Article.processing_state == "embedded")
        .where(Article.embedding.isnot(None))
        .order_by(Article.published_at.asc(), Article.id.asc())
        .limit(batch_limit)
    )
    articles = list(session.scalars(q))
    if not articles:
        return ClusterOutcome(0, 0, 0)

    log.info("cluster: %d candidates in state=embedded", len(articles))

    attached = 0
    new_stories = 0

    # Raw SQL for the neighbor query — we need pgvector's `<=>` operator
    # and want to pass the embedding as a positional param without going
    # through the ORM's list-serialization surprises.
    #
    # We look at articles that already have story_id (clustered/analyzed/
    # complete) AND were published in the lookback window. LIMIT 1 by
    # smallest cosine distance = highest similarity.
    neighbor_sql = text("""
        SELECT a.story_id,
               1 - (a.embedding <=> CAST(:vec AS vector)) AS similarity
          FROM articles a
         WHERE a.story_id IS NOT NULL
           AND a.embedding IS NOT NULL
           AND a.published_at >= NOW() - (:lookback_days || ' days')::interval
         ORDER BY a.embedding <=> CAST(:vec AS vector) ASC
         LIMIT 1
    """)

    now = datetime.now(tz=timezone.utc)

    for article in articles:
        # pgvector accepts a stringified list "[0.1, 0.2, ...]".
        vec_str = _vec_literal(article.embedding)

        neighbor = session.execute(
            neighbor_sql, {"vec": vec_str, "lookback_days": lookback_days}
        ).first()

        if neighbor is not None and neighbor.similarity is not None \
                and float(neighbor.similarity) >= threshold:
            story_id = int(neighbor.story_id)
            log.info(
                "cluster: article_id=%s → story_id=%s (sim=%.3f)",
                article.id, story_id, float(neighbor.similarity),
            )
            attached += 1
        else:
            # No sufficiently-similar recent story — start a new one.
            story = Story(
                title=article.headline[:500],
                topic=None,
                first_seen_at=article.published_at,
                last_seen_at=article.published_at,
                article_count=0,   # incremented below
                summary=None,
            )
            session.add(story)
            session.flush()
            story_id = story.id
            new_stories += 1
            log.info(
                "cluster: article_id=%s → new story_id=%s (best_sim=%s)",
                article.id, story_id,
                f"{float(neighbor.similarity):.3f}" if neighbor else "n/a",
            )

        # Attach article, advance state, bump story bookkeeping.
        session.execute(
            update(Article)
            .where(Article.id == article.id)
            .values(
                story_id=story_id,
                processing_state="clustered",
                state_updated_at=now,
                state_error=None,
                attempt_count=0,
            )
        )
        session.execute(
            update(Story)
            .where(Story.id == story_id)
            .values(
                article_count=Story.article_count + 1,
                last_seen_at=_max_ts(Story.last_seen_at, article.published_at),
            )
        )

    session.commit()

    log.info("cluster: attached=%d new_stories=%d",
             attached, new_stories)
    return ClusterOutcome(
        articles_clustered=len(articles),
        new_stories=new_stories,
        attached_to_existing=attached,
    )


def _vec_literal(embedding: Sequence[float] | list[float]) -> str:
    """Format a Python vector as a pgvector literal string."""
    return "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"


def _max_ts(existing_col, candidate: datetime):
    """SQL: GREATEST(existing_col, candidate_ts) — case-agnostic."""
    from sqlalchemy import func
    return func.greatest(existing_col, candidate)
