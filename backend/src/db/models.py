"""SQLAlchemy 2.0 ORM models mirroring the schema in architecture §9.

Populated alongside migration `0001_initial_schema` (Week 1, step 4).
This file is intentionally empty during the scaffold step so that model
authoring and the initial migration land in the same reviewable change.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all NewsLens ORM models."""


# Concrete models (Outlet, Story, AnalysisRun, Article, ArticleAnalysis,
# StoryComparison, StoryOverride, IngestionRun, EvalLabel) are added in the
# next commit together with alembic/versions/0001_initial_schema.py.
