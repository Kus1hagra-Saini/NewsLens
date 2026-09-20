"""SQLAlchemy 2.0 ORM models mirroring the schema in architecture §9.

Table classes are declared in the dependency order the initial migration
uses so anyone reading top-to-bottom sees FKs after their targets:

    outlets → stories → analysis_runs → articles → article_analysis
           → story_comparisons → story_overrides → ingestion_runs → eval_labels

Implementation corrections (see docs/architecture.md change log, 2026-09-20):
  1. article_analysis.article_id is the sole PK (latest-wins).
  2. articles.attempt_count backs the documented 3-failure retry rule.
  3. outlet_30d_stats view SQL lives in the migration, not here.

Note on indexes: DESC-ordered btree indexes, the pgvector ivfflat index,
and the tsvector gin index are declared **only** in the initial migration.
SQLAlchemy autogenerate cannot round-trip these expression forms cleanly
(`sa.text("col DESC")`, `postgresql_using="ivfflat"` with an ops class),
so keeping them out of `__table_args__` avoids spurious `alembic check`
drift while still creating them correctly at migration time. The plain
btree indexes on `articles.story_id`, `stories.topic`, etc. stay here so
autogenerate can manage any future changes to them.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# --- ENUM ------------------------------------------------------------------
# The enum type is created and dropped explicitly by the Alembic migration
# (create_type=False here) so alembic controls the type's lifecycle without
# double-creating it from the ORM metadata.
PROCESSING_STATE_VALUES = (
    "discovered",
    "extracted",
    "embedded",
    "clustered",
    "analyzed",
    "complete",
    "failed_extract",
    "failed_embed",
    "failed_analyze",
)

processing_state_enum = ENUM(
    *PROCESSING_STATE_VALUES,
    name="processing_state",
    create_type=False,
)


class Base(DeclarativeBase):
    """Declarative base for all NewsLens ORM models."""


# --- 1. outlets -----------------------------------------------------------
class Outlet(Base):
    __tablename__ = "outlets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    rss_url: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[str] = mapped_column(Text, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# --- 2. stories -----------------------------------------------------------
class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # ix_stories_last_seen_at_desc (DESC-ordered) lives in the migration.
        Index("ix_stories_topic", "topic"),
    )


# --- 3. analysis_runs -----------------------------------------------------
class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('enrich', 'compare')",
            name="analysis_runs_purpose_check",
        ),
    )


# --- 4. articles ----------------------------------------------------------
class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    outlet_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("outlets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    full_text: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[Any | None] = mapped_column(Vector(384))
    story_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("stories.id", ondelete="SET NULL"),
    )
    processing_state: Mapped[str] = mapped_column(
        processing_state_enum,
        nullable=False,
        server_default="discovered",
    )
    state_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    state_error: Mapped[str | None] = mapped_column(Text)

    # Retry counter that backs the documented 3-failure rule (Appendix A).
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Generated tsvector for full-text search on headline + body.
    fts: Mapped[Any | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(headline, '') || ' ' || coalesce(full_text, ''))",
            persisted=True,
        ),
    )

    __table_args__ = (
        # ix_articles_outlet_published (DESC on published_at),
        # ix_articles_embedding_ivfflat (pgvector), and
        # ix_articles_fts_gin (tsvector) live in the migration.
        Index("ix_articles_story_id", "story_id"),
    )


# --- 5. article_analysis --------------------------------------------------
class ArticleAnalysis(Base):
    __tablename__ = "article_analysis"

    # Sole PK — confirmed latest-wins per owner decision on 2026-09-20.
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    analysis_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("analysis_runs.id"),
        nullable=False,
    )
    framing_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    framing_label: Mapped[str | None] = mapped_column(Text)
    framing_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    headline_sentiment: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    body_sentiment: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    key_themes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    entities: Mapped[dict | None] = mapped_column(JSONB)
    quoted_sources: Mapped[list | None] = mapped_column(JSONB)
    source_distribution: Mapped[dict | None] = mapped_column(JSONB)
    evidence_snippets: Mapped[list | None] = mapped_column(JSONB)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "framing_score IS NULL OR (framing_score BETWEEN -1 AND 1)",
            name="article_analysis_framing_score_check",
        ),
        CheckConstraint(
            "framing_confidence IS NULL OR (framing_confidence BETWEEN 0 AND 1)",
            name="article_analysis_framing_confidence_check",
        ),
        CheckConstraint(
            "headline_sentiment IS NULL OR (headline_sentiment BETWEEN -1 AND 1)",
            name="article_analysis_headline_sentiment_check",
        ),
        CheckConstraint(
            "body_sentiment IS NULL OR (body_sentiment BETWEEN -1 AND 1)",
            name="article_analysis_body_sentiment_check",
        ),
        CheckConstraint(
            "framing_label IS NULL OR framing_label IN "
            "('critical','neutral','supportive','mixed','insufficient')",
            name="article_analysis_framing_label_check",
        ),
    )


# --- 6. story_comparisons -------------------------------------------------
class StoryComparison(Base):
    __tablename__ = "story_comparisons"

    story_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("stories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    analysis_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("analysis_runs.id"),
        nullable=False,
    )
    differences: Mapped[str] = mapped_column(Text, nullable=False)
    framing_spread: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    coverage_matrix: Mapped[dict | None] = mapped_column(JSONB)
    not_present_here: Mapped[dict | None] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- 7. story_overrides ---------------------------------------------------
class StoryOverride(Base):
    __tablename__ = "story_overrides"

    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    forced_story_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("stories.id", ondelete="SET NULL"),
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    overridden_by: Mapped[str] = mapped_column(Text, nullable=False)
    overridden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- 8. ingestion_runs ----------------------------------------------------
class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False)
    articles_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    articles_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    articles_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "triggered_by IN ('cron', 'manual', 'backfill')",
            name="ingestion_runs_triggered_by_check",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'skipped')",
            name="ingestion_runs_status_check",
        ),
        # ix_ingestion_runs_started_at_desc (DESC-ordered) lives in the migration.
    )


# --- 9. eval_labels -------------------------------------------------------
class EvalLabel(Base):
    __tablename__ = "eval_labels"

    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    labeled_by: Mapped[str] = mapped_column(Text, nullable=False)
    labeled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expected_framing: Mapped[str] = mapped_column(Text, nullable=False)
    expected_sentiment: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    expected_entities: Mapped[dict | None] = mapped_column(JSONB)
