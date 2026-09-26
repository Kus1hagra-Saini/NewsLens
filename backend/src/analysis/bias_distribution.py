"""Media Bias Distribution — story-level aggregation of publication-level ratings.

Pure functions only: no DB, no async, no framework. The API route builds
the inputs (loading outlets, rating rows, source-priority list) and hands
them to :func:`compute_bias_distribution`, which returns a structured
result ready to serialise.

Terminology
-----------
This module deliberately never uses "story bias" or similar. The
distribution describes the *population of rated outlets covering a
story*, not the story or its articles.

Eligibility rules (from the product spec)
-----------------------------------------
1. Story must have coverage from at least 3 DISTINCT outlets.
2. At least 3 of those outlets must have a usable bias rating from
   ``SOURCE_PRIORITY``.

The frontend never sees a partial or fake bar: when eligibility fails,
the response reports ``eligible=false`` and the frontend can show the
reason instead of the visualisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Literal

from src.ingestion.bias_ratings import (
    SOURCE_PRIORITY,
    BiasCategory,
    normalize_label,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MIN_OUTLETS_FOR_ELIGIBILITY: int = 3
MIN_RATED_OUTLETS_FOR_ELIGIBILITY: int = 3


IneligibleReason = Literal[
    "too_few_outlets",       # <3 distinct outlets in the story
    "too_few_rated_outlets", # <3 rated outlets covering the story
]


# ---------------------------------------------------------------------------
# Input records — plain data the API route can populate from ORM rows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutletRatingRow:
    """One (outlet, source) rating row, as stored in outlet_bias_ratings.

    ``normalized_category`` may be ``None`` if the row was inserted
    before the current label mapping knew about the label — we
    re-normalise defensively below anyway.
    """
    outlet_id: int
    outlet_slug: str
    outlet_name: str
    source: str
    original_label: str
    normalized_category: BiasCategory | None
    rating_url: str
    rated_at: datetime | None


@dataclass(frozen=True)
class OutletInStory:
    """One outlet participating in the story (distinct — dedupe on caller)."""
    id: int
    slug: str
    name: str


# ---------------------------------------------------------------------------
# Output records — mirror the API schema shape
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BiasDistributionSourceRow:
    outlet_id: int
    outlet_slug: str
    outlet_name: str
    original_rating: str
    normalized_category: BiasCategory
    rating_source: str
    rating_url: str
    rated_at: datetime | None


@dataclass(frozen=True)
class BiasDistributionResult:
    eligible: bool
    reason: IneligibleReason | None
    total_outlet_count: int
    rated_outlet_count: int
    unrated_outlet_count: int
    unrated_outlet_slugs: tuple[str, ...]
    # Percentages that sum to 100 (subject to rounding). All three keys
    # are always present, even when a category has zero outlets.
    distribution: dict[BiasCategory, float]
    # Raw category counts, useful for the frontend's "N outlets" line.
    counts: dict[BiasCategory, int]
    # One record per rated outlet used in the distribution (the source
    # chosen by SOURCE_PRIORITY). Provides the source-details view.
    sources: tuple[BiasDistributionSourceRow, ...]


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_bias_distribution(
    outlets: Iterable[OutletInStory],
    ratings: Iterable[OutletRatingRow],
    source_priority: tuple[str, ...] = SOURCE_PRIORITY,
) -> BiasDistributionResult:
    """Aggregate publication-level ratings into a story-level distribution.

    ``outlets`` — the DISTINCT outlets covering the story. Multi-article
    outlets must appear once; this function does not dedupe them for you
    (the API route does that via SELECT DISTINCT), so an outlet is
    counted once regardless of how many articles it published.

    ``ratings`` — every rating row for those outlets. May include several
    rows per outlet (multiple sources). This function picks one per
    outlet using ``source_priority``.

    Returns a fully-populated :class:`BiasDistributionResult`. Never
    raises for empty inputs — an empty story is simply ineligible.
    """
    # Deduplicate outlets defensively.
    outlets_by_id: dict[int, OutletInStory] = {}
    for o in outlets:
        outlets_by_id.setdefault(o.id, o)
    outlets_list = list(outlets_by_id.values())
    total_outlet_count = len(outlets_list)

    empty_distribution: dict[BiasCategory, float] = {
        "left": 0.0, "center": 0.0, "right": 0.0,
    }
    empty_counts: dict[BiasCategory, int] = {"left": 0, "center": 0, "right": 0}

    # Not enough outlets covering the story to even consider the bar.
    if total_outlet_count < MIN_OUTLETS_FOR_ELIGIBILITY:
        return BiasDistributionResult(
            eligible=False,
            reason="too_few_outlets",
            total_outlet_count=total_outlet_count,
            rated_outlet_count=0,
            unrated_outlet_count=total_outlet_count,
            unrated_outlet_slugs=tuple(sorted(o.slug for o in outlets_list)),
            distribution=empty_distribution,
            counts=empty_counts,
            sources=(),
        )

    # Group ratings by outlet_id, and within each outlet pick the
    # winning source according to source_priority. Sources not in the
    # priority list are ignored for the distribution (still returned by
    # the API in a future "all ratings" view if desired).
    priority_index = {src: i for i, src in enumerate(source_priority)}
    ratings_by_outlet: dict[int, list[OutletRatingRow]] = {}
    for r in ratings:
        if r.outlet_id not in outlets_by_id:
            # Ignore ratings for outlets not in this story.
            continue
        if r.source not in priority_index:
            continue
        ratings_by_outlet.setdefault(r.outlet_id, []).append(r)

    chosen_by_outlet: dict[int, OutletRatingRow] = {}
    for outlet_id, rows in ratings_by_outlet.items():
        # Sort by priority index (lower index = higher priority).
        rows.sort(key=lambda r: priority_index[r.source])
        primary = rows[0]

        # Re-derive the normalised category from the raw label. This
        # ensures a stale enum stored in the DB doesn't override the
        # current mapping. If the current mapping doesn't cover the
        # stored label, the outlet is treated as unrated.
        normalised = normalize_label(primary.source, primary.original_label)
        if normalised is None:
            # Fall back to the DB's stored normalisation if it exists
            # AND is one of the recognised buckets.
            if primary.normalized_category in ("left", "center", "right"):
                normalised = primary.normalized_category
            else:
                continue

        # Freeze the freshly-derived category by replacing the row's
        # normalised_category field. Dataclass is frozen, so use
        # dataclasses.replace equivalent (manual construction).
        chosen_by_outlet[outlet_id] = OutletRatingRow(
            outlet_id=primary.outlet_id,
            outlet_slug=primary.outlet_slug,
            outlet_name=primary.outlet_name,
            source=primary.source,
            original_label=primary.original_label,
            normalized_category=normalised,
            rating_url=primary.rating_url,
            rated_at=primary.rated_at,
        )

    rated_outlet_count = len(chosen_by_outlet)
    unrated_outlet_count = total_outlet_count - rated_outlet_count
    unrated_outlet_slugs = tuple(sorted(
        o.slug for o in outlets_list if o.id not in chosen_by_outlet
    ))

    # Not enough rated outlets to show a bar; report as ineligible.
    if rated_outlet_count < MIN_RATED_OUTLETS_FOR_ELIGIBILITY:
        return BiasDistributionResult(
            eligible=False,
            reason="too_few_rated_outlets",
            total_outlet_count=total_outlet_count,
            rated_outlet_count=rated_outlet_count,
            unrated_outlet_count=unrated_outlet_count,
            unrated_outlet_slugs=unrated_outlet_slugs,
            distribution=empty_distribution,
            counts=empty_counts,
            sources=(),
        )

    # Count categories across the chosen ratings.
    counts: dict[BiasCategory, int] = {"left": 0, "center": 0, "right": 0}
    for row in chosen_by_outlet.values():
        # ``normalized_category`` cannot be None here (we filtered above).
        counts[row.normalized_category] += 1  # type: ignore[index]

    distribution: dict[BiasCategory, float] = {
        cat: round(counts[cat] / rated_outlet_count * 100.0, 2)
        for cat in ("left", "center", "right")
    }

    # Order the sources view by category (left → center → right), then
    # by outlet name — stable and human-readable.
    category_order = {"left": 0, "center": 1, "right": 2}
    ordered_sources = tuple(
        BiasDistributionSourceRow(
            outlet_id=row.outlet_id,
            outlet_slug=row.outlet_slug,
            outlet_name=row.outlet_name,
            original_rating=row.original_label,
            normalized_category=row.normalized_category,  # type: ignore[arg-type]
            rating_source=row.source,
            rating_url=row.rating_url,
            rated_at=row.rated_at,
        )
        for row in sorted(
            chosen_by_outlet.values(),
            key=lambda r: (
                category_order[r.normalized_category],  # type: ignore[index]
                r.outlet_name.lower(),
            ),
        )
    )

    return BiasDistributionResult(
        eligible=True,
        reason=None,
        total_outlet_count=total_outlet_count,
        rated_outlet_count=rated_outlet_count,
        unrated_outlet_count=unrated_outlet_count,
        unrated_outlet_slugs=unrated_outlet_slugs,
        distribution=distribution,
        counts=counts,
        sources=ordered_sources,
    )
