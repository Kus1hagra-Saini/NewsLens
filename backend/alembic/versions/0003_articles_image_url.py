"""articles.image_url — publication-supplied image URL

Adds a nullable ``image_url`` column to ``articles``. Populated
during ingestion from RSS/media, ``og:image``, or ``twitter:image``.
NewsLens never downloads or rehosts the image; only the URL is stored
so the frontend can load it directly from the outlet.

The column is nullable because not every article carries a usable
image. UI code hides the image slot when the field is NULL rather
than displaying a placeholder.

An index on ``articles(image_url) WHERE image_url IS NULL`` supports
the backfill job's primary query pattern. It stays small (only NULL
rows are indexed) and is dropped implicitly once no rows match.

Revision ID: 0003_articles_image_url
Revises: 0002_outlet_bias_ratings
Create Date: 2026-09-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003_articles_image_url"
down_revision: Union[str, None] = "0002_outlet_bias_ratings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("image_url", sa.Text(), nullable=True),
    )
    # Partial index for the backfill job. Only indexes rows still
    # missing an image, so it stays cheap.
    op.create_index(
        "ix_articles_image_url_null",
        "articles",
        ["id"],
        unique=False,
        postgresql_where=sa.text("image_url IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_articles_image_url_null", table_name="articles")
    op.drop_column("articles", "image_url")
