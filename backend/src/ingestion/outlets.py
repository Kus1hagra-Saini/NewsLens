"""Outlet registry loader.

Reads `src/ingestion/outlets.yaml` and returns Outlet records for one or
more phases. Kept separate from the ORM model so the yaml can be edited
without touching db/models.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

_OUTLETS_YAML = Path(__file__).parent / "outlets.yaml"


@dataclass(frozen=True)
class OutletSpec:
    slug: str
    name: str
    rss_url: str
    website: str
    logo_url: str | None = None


def load_outlets(phases: Iterable[str] = ("phase_1",)) -> list[OutletSpec]:
    """Load outlet specs for the given phases, in yaml order."""
    with _OUTLETS_YAML.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: list[OutletSpec] = []
    for phase in phases:
        for raw in data.get(phase, []):
            out.append(
                OutletSpec(
                    slug=raw["slug"],
                    name=raw["name"],
                    rss_url=raw["rss_url"],
                    website=raw["website"],
                    logo_url=raw.get("logo_url"),
                )
            )
    return out
