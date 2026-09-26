"""outlet_bias_ratings — publication-level external bias ratings

Introduces the ``outlet_bias_ratings`` table plus the ``bias_category``
enum. Rows are populated by ``python -m src.ingestion.seed_bias_ratings``
from an external, documented source (currently only MBFC).

Design notes
------------
- Normalized (one row per outlet × source). Multiple sources per outlet
  are supported without destroying provenance.
- ``original_label`` is preserved verbatim so the API can show the raw
  external claim; ``normalized_category`` is a deterministic mapping to
  one of (left, center, right) used for the aggregate distribution.
- ``rated_at`` is when the external source last updated the rating;
  ``recorded_at`` is when NewsLens saved this row. Both help viewers
  judge how current the rating is.
- The unique index on (outlet_id, source) enforces the "one row per
  (outlet, source)" rule.

Revision ID: 0002_outlet_bias_ratings
Revises: 0001_initial_schema
Create Date: 2026-09-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0002_outlet_bias_ratings"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BIAS_CATEGORY_VALUES = ("left", "center", "right")


def upgrade() -> None:
    # ENUM type — created explicitly so downgrade can drop it cleanly.
    bias_category = postgresql.ENUM(
        *BIAS_CATEGORY_VALUES,
        name="bias_category",
        create_type=False,
    )
    bias_category.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "outlet_bias_ratings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "outlet_id",
            sa.Integer(),
            sa.ForeignKey("outlets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("original_label", sa.Text(), nullable=False),
        sa.Column(
            "normalized_category",
            postgresql.ENUM(
                *BIAS_CATEGORY_VALUES,
                name="bias_category",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("rating_url", sa.Text(), nullable=False),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ux_outlet_bias_ratings_outlet_source",
        "outlet_bias_ratings",
        ["outlet_id", "source"],
        unique=True,
    )
    # Helper index for "list all ratings covering these outlets" — the
    # story-detail endpoint's primary access pattern.
    op.create_index(
        "ix_outlet_bias_ratings_outlet_id",
        "outlet_bias_ratings",
        ["outlet_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outlet_bias_ratings_outlet_id",
        table_name="outlet_bias_ratings",
    )
    op.drop_index(
        "ux_outlet_bias_ratings_outlet_source",
        table_name="outlet_bias_ratings",
    )
    op.drop_table("outlet_bias_ratings")

    bias_category = postgresql.ENUM(
        *BIAS_CATEGORY_VALUES,
        name="bias_category",
        create_type=False,
    )
    bias_category.drop(op.get_bind(), checkfirst=True)
