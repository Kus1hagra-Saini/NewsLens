"""eval API router. Wired in Week 3 per architecture §13."""

from fastapi import APIRouter

router = APIRouter(prefix="/eval", tags=["eval"])
