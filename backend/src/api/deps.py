"""Shared FastAPI dependencies and validators for the API layer."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session


MAX_LIMIT = 100
DEFAULT_LIMIT = 20


def pagination(
    page:  int = Query(1,             ge=1),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> dict[str, int]:
    """Uniform pagination parameters. Enforces sane bounds."""
    return {"page": page, "limit": limit, "offset": (page - 1) * limit}


Session = Annotated[AsyncSession, Depends(get_session)]
Pagination = Annotated[dict[str, int], Depends(pagination)]
