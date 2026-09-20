"""initial schema — architecture v2, week 1

Creates every object in architecture §9:
    - extension `vector`
    - ENUM type `processing_state`
    - 9 tables in dependency order:
        outlets, stories, analysis_runs, articles, article_analysis,
        story_comparisons, story_overrides, ingestion_runs, eval_labels
    - every documented index (btree, ivfflat, gin)
    - the corrected `outlet_30d_stats` materialized view + its unique index

Implementation corrections (agreed 2026-09-20, see docs/architecture.md):
    - `article_analysis.article_id` is the sole PK (latest-wins).
    - `articles.attempt_count INT NOT NULL DEFAULT 0` added.
    - Tables created in dependency order.
    - `outlet_30d_stats.top_themes` now produces `{theme: count}` correctly.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def upgrade() -> None:
    # --- Extensions ------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- Enum types ------------------------------------------------------
    processing_state = postgresql.ENUM(
        *PROCESSING_STATE_VALUES,
        name="processing_state",
        create_type=False,
    )
    processing_state.create(op.get_bind(), checkfirst=True)

    # --- 1. outlets ------------------------------------------------------
    op.create_table(
        "outlets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("rss_url", sa.Text(), nullable=False),
        sa.Column("website", sa.Text(), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
    )

    # --- 2. stories ------------------------------------------------------
    op.create_table(
        "stories",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "article_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("summary", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_stories_last_seen_at_desc",
        "stories",
        [sa.text("last_seen_at DESC")],
    )
    op.create_index("ix_stories_topic", "stories", ["topic"])

    # --- 3. analysis_runs ------------------------------------------------
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "ran_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('enrich', 'compare')",
            name="analysis_runs_purpose_check",
        ),
    )

    # --- 4. articles -----------------------------------------------------
    op.create_table(
        "articles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "outlet_id",
            sa.Integer(),
            sa.ForeignKey("outlets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column(
            "story_id",
            sa.BigInteger(),
            sa.ForeignKey("stories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "processing_state",
            postgresql.ENUM(name="processing_state", create_type=False),
            nullable=False,
            server_default=sa.text("'discovered'::processing_state"),
        ),
        sa.Column(
            "state_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("state_error", sa.Text(), nullable=True),
        # Retry counter that backs the documented 3-failure rule.
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        # Generated column: tsvector over headline + full_text.
        sa.Column(
            "fts",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(headline, '') || ' ' || "
                "coalesce(full_text, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_articles_outlet_published",
        "articles",
        ["outlet_id", sa.text("published_at DESC")],
    )
    op.create_index("ix_articles_story_id", "articles", ["story_id"])
    # pgvector ivfflat index. Cosine ops match the doc's distance function.
    op.execute(
        "CREATE INDEX ix_articles_embedding_ivfflat "
        "ON articles USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.create_index(
        "ix_articles_fts_gin",
        "articles",
        ["fts"],
        postgresql_using="gin",
    )

    # --- 5. article_analysis ---------------------------------------------
    # article_id is the SOLE PK (latest-wins model, confirmed by owner).
    op.create_table(
        "article_analysis",
        sa.Column(
            "article_id",
            sa.BigInteger(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "analysis_run_id",
            sa.BigInteger(),
            sa.ForeignKey("analysis_runs.id"),
            nullable=False,
        ),
        sa.Column("framing_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("framing_label", sa.Text(), nullable=True),
        sa.Column("framing_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("headline_sentiment", sa.Numeric(3, 2), nullable=True),
        sa.Column("body_sentiment", sa.Numeric(3, 2), nullable=True),
        sa.Column("key_themes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("entities", postgresql.JSONB(), nullable=True),
        sa.Column("quoted_sources", postgresql.JSONB(), nullable=True),
        sa.Column("source_distribution", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_snippets", postgresql.JSONB(), nullable=True),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "framing_score IS NULL OR (framing_score BETWEEN -1 AND 1)",
            name="article_analysis_framing_score_check",
        ),
        sa.CheckConstraint(
            "framing_confidence IS NULL OR (framing_confidence BETWEEN 0 AND 1)",
            name="article_analysis_framing_confidence_check",
        ),
        sa.CheckConstraint(
            "headline_sentiment IS NULL OR (headline_sentiment BETWEEN -1 AND 1)",
            name="article_analysis_headline_sentiment_check",
        ),
        sa.CheckConstraint(
            "body_sentiment IS NULL OR (body_sentiment BETWEEN -1 AND 1)",
            name="article_analysis_body_sentiment_check",
        ),
        sa.CheckConstraint(
            "framing_label IS NULL OR framing_label IN "
            "('critical','neutral','supportive','mixed','insufficient')",
            name="article_analysis_framing_label_check",
        ),
    )

    # --- 6. story_comparisons --------------------------------------------
    op.create_table(
        "story_comparisons",
        sa.Column(
            "story_id",
            sa.BigInteger(),
            sa.ForeignKey("stories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "analysis_run_id",
            sa.BigInteger(),
            sa.ForeignKey("analysis_runs.id"),
            nullable=False,
        ),
        sa.Column("differences", sa.Text(), nullable=False),
        sa.Column("framing_spread", sa.Numeric(3, 2), nullable=True),
        sa.Column("coverage_matrix", postgresql.JSONB(), nullable=True),
        sa.Column("not_present_here", postgresql.JSONB(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # --- 7. story_overrides ----------------------------------------------
    op.create_table(
        "story_overrides",
        sa.Column(
            "article_id",
            sa.BigInteger(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "forced_story_id",
            sa.BigInteger(),
            sa.ForeignKey("stories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("overridden_by", sa.Text(), nullable=False),
        sa.Column(
            "overridden_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # --- 8. ingestion_runs -----------------------------------------------
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by", sa.Text(), nullable=False),
        sa.Column(
            "articles_discovered",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "articles_inserted",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "articles_failed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "llm_calls",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "triggered_by IN ('cron', 'manual', 'backfill')",
            name="ingestion_runs_triggered_by_check",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'skipped')",
            name="ingestion_runs_status_check",
        ),
    )
    op.create_index(
        "ix_ingestion_runs_started_at_desc",
        "ingestion_runs",
        [sa.text("started_at DESC")],
    )

    # --- 9. eval_labels --------------------------------------------------
    op.create_table(
        "eval_labels",
        sa.Column(
            "article_id",
            sa.BigInteger(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("labeled_by", sa.Text(), nullable=False),
        sa.Column(
            "labeled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expected_framing", sa.Text(), nullable=False),
        sa.Column("expected_sentiment", sa.Numeric(3, 2), nullable=True),
        sa.Column("expected_entities", postgresql.JSONB(), nullable=True),
    )

    # --- outlet_30d_stats (materialized view) ----------------------------
    # Correction over the architecture doc's printed SQL:
    #   The doc's LATERAL ... unnest(aa.key_themes) AS k, 1 AS v feeding
    #   jsonb_object_agg(k, v) collapses duplicates last-value-wins, losing
    #   theme frequency. We aggregate to (outlet_id, theme, cnt) first, then
    #   fold that into jsonb_object_agg(theme, cnt) — so `top_themes` is a
    #   {theme: count} map, which is presumably what "top_themes" means.
    op.execute("""
        CREATE MATERIALIZED VIEW outlet_30d_stats AS
        WITH per_outlet AS (
            SELECT
                a.outlet_id,
                COUNT(*)                                    AS article_count,
                ROUND(AVG(aa.framing_score)::numeric, 2)    AS avg_framing,
                ROUND(AVG(aa.body_sentiment)::numeric, 2)   AS avg_sentiment
            FROM articles a
            JOIN article_analysis aa ON aa.article_id = a.id
            WHERE a.published_at >= NOW() - INTERVAL '30 days'
            GROUP BY a.outlet_id
        ),
        per_theme AS (
            SELECT
                a.outlet_id,
                theme,
                COUNT(*) AS cnt
            FROM articles a
            JOIN article_analysis aa ON aa.article_id = a.id
            LEFT JOIN LATERAL unnest(aa.key_themes) AS theme ON TRUE
            WHERE a.published_at >= NOW() - INTERVAL '30 days'
              AND theme IS NOT NULL
            GROUP BY a.outlet_id, theme
        ),
        themes_agg AS (
            SELECT
                outlet_id,
                jsonb_object_agg(theme, cnt) AS top_themes
            FROM per_theme
            GROUP BY outlet_id
        )
        SELECT
            po.outlet_id,
            po.article_count,
            po.avg_framing,
            po.avg_sentiment,
            COALESCE(ta.top_themes, '{}'::jsonb) AS top_themes
        FROM per_outlet po
        LEFT JOIN themes_agg ta USING (outlet_id)
    """)
    # UNIQUE index required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
    op.execute(
        "CREATE UNIQUE INDEX ix_outlet_30d_stats_outlet_id "
        "ON outlet_30d_stats (outlet_id)"
    )


def downgrade() -> None:
    # Reverse dependency order.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS outlet_30d_stats")
    op.drop_table("eval_labels")
    op.drop_index("ix_ingestion_runs_started_at_desc", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("story_overrides")
    op.drop_table("story_comparisons")
    op.drop_table("article_analysis")
    op.drop_index("ix_articles_fts_gin", table_name="articles")
    op.execute("DROP INDEX IF EXISTS ix_articles_embedding_ivfflat")
    op.drop_index("ix_articles_story_id", table_name="articles")
    op.drop_index("ix_articles_outlet_published", table_name="articles")
    op.drop_table("articles")
    op.drop_table("analysis_runs")
    op.drop_index("ix_stories_topic", table_name="stories")
    op.drop_index("ix_stories_last_seen_at_desc", table_name="stories")
    op.drop_table("stories")
    op.drop_table("outlets")

    postgresql.ENUM(name="processing_state").drop(op.get_bind(), checkfirst=True)
    # Extension `vector` is left in place — Neon manages it; dropping would
    # break any other schema on the same DB using vectors.
