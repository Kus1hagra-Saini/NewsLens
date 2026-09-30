"""Unit tests for the publication-level Media Bias Distribution.

Every test here is pure Python — no database, no HTTP. The API-level
integration test lives in ``test_api.py`` and uses the ``db_session`` +
``api_client`` fixtures.

The spec's test checklist is followed one-for-one; each test's docstring
names the requirement it covers.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.analysis.bias_distribution import (
    OutletInStory,
    OutletRatingRow,
    compute_bias_distribution,
)
from src.ingestion.bias_ratings import (
    RATINGS,
    SOURCE_PRIORITY,
    normalize_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _outlet(id_: int, slug: str, name: str | None = None) -> OutletInStory:
    return OutletInStory(id=id_, slug=slug, name=name or slug.title())


def _rating(
    outlet_id: int,
    slug: str,
    label: str,
    category: str,
    source: str = "MBFC",
    name: str | None = None,
) -> OutletRatingRow:
    return OutletRatingRow(
        outlet_id=outlet_id,
        outlet_slug=slug,
        outlet_name=name or slug.title(),
        source=source,
        original_label=label,
        normalized_category=category,  # type: ignore[arg-type]
        rating_url=f"https://example/{slug}",
        rated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


# =============================================================================
# Normalization — spec test 6
# =============================================================================

def test_normalize_label_supported_mbfc_labels():
    """normalize_label maps every supported MBFC label deterministically."""
    assert normalize_label("MBFC", "Left")         == "left"
    assert normalize_label("MBFC", "Left-Center")  == "left"
    assert normalize_label("MBFC", "left-center")  == "left"  # case-insensitive
    assert normalize_label("MBFC", "Least Biased") == "center"
    assert normalize_label("MBFC", "Center")       == "center"
    assert normalize_label("MBFC", "Right-Center") == "right"
    assert normalize_label("MBFC", "Right")        == "right"


def test_normalize_label_unknown_label_returns_none():
    """An unfamiliar label returns None — never an invented mapping."""
    assert normalize_label("MBFC", "Extremely Purple") is None
    assert normalize_label("MBFC", "") is None
    assert normalize_label("MBFC", "  ") is None


def test_normalize_label_unknown_source_returns_none():
    """A source we haven't seen returns None — never a guess."""
    assert normalize_label("MadeUpSource", "Left-Center") is None
    assert normalize_label("", "Left") is None


def test_normalize_label_strips_and_lowercases():
    """Leading/trailing whitespace and case should not defeat the map."""
    assert normalize_label("MBFC", "  LEFT-CENTER  ") == "left"


# =============================================================================
# Seed data sanity — every RATINGS entry must normalise cleanly
# =============================================================================

def test_every_seed_rating_normalises_to_a_bucket():
    """RATINGS is hand-recorded; if any entry can't map, the seed will
    silently skip it. Fail fast in the test suite instead."""
    for r in RATINGS:
        cat = normalize_label(r.source, r.original_label)
        assert cat in ("left", "center", "right"), (
            f"RATINGS entry does not normalise: {r.outlet_slug} "
            f"source={r.source} label={r.original_label!r}"
        )


def test_source_priority_is_nonempty():
    """SOURCE_PRIORITY must list at least one source or the bar is dead."""
    assert isinstance(SOURCE_PRIORITY, tuple)
    assert len(SOURCE_PRIORITY) >= 1
    assert all(isinstance(s, str) and s for s in SOURCE_PRIORITY)


# =============================================================================
# Full-coverage of phase_1 outlets (added 2026-09-30 with the
# 10-outlet expansion — every configured outlet must ship with a
# documented external rating so the Media Bias Distribution stays
# eligible for the majority of stories, without lowering the 3-rated
# threshold the spec requires).
# =============================================================================

# Expected mapping — MBFC raw label → NewsLens display bucket. Keeps
# the researched input auditable in one place; if a rating is ever
# changed at MBFC, the test fails and forces a review of the source.
EXPECTED_MBFC_PHASE_1: dict[str, tuple[str, str]] = {
    # outlet_slug: (mbfc_original_label, normalized_category)
    # ── Original five ──
    "the-hindu":         ("Left-Center",  "left"),
    "times-of-india":    ("Right-Center", "right"),
    "indian-express":    ("Left-Center",  "left"),
    "ndtv":              ("Right-Center", "right"),
    "hindustan-times":   ("Left-Center",  "left"),
    # ── Phase-1 expansion (added 2026-09-30) ──
    "india-today":       ("Right-Center", "right"),
    "theprint":          ("Right-Center", "right"),
    "livemint":          ("Least Biased", "center"),
    "economic-times":    ("Right-Center", "right"),
    "news18":            ("Right-Center", "right"),
    "the-wire":          ("Left-Center",  "left"),
    "scroll-in":         ("Left-Center",  "left"),
    "tribune-india":     ("Right-Center", "right"),
    "business-standard": ("Right-Center", "right"),
    "financial-express": ("Right-Center", "right"),
}


def test_ratings_cover_every_phase_1_outlet():
    """Every outlet declared active in phase_1 must have a documented
    MBFC rating in RATINGS. Anything missing means the Media Bias
    Distribution will silently degrade to "not enough rated coverage"
    for stories including that outlet — regression guard against
    forgetting to add a rating when a new outlet is onboarded."""
    from src.ingestion.outlets import load_outlets

    yaml_slugs = {spec.slug for spec in load_outlets(["phase_1"])}
    rated_slugs = {r.outlet_slug for r in RATINGS if r.source == "MBFC"}
    missing = yaml_slugs - rated_slugs
    assert not missing, (
        f"phase_1 outlets missing MBFC rating in bias_ratings.RATINGS: "
        f"{sorted(missing)}"
    )


def test_no_ratings_for_undeclared_outlets():
    """RATINGS must not contain ghost slugs that no outlet in
    outlets.yaml references — those would be dead entries the seed
    would silently skip with 'outlet not present'."""
    from src.ingestion.outlets import load_outlets

    yaml_slugs = {spec.slug for spec in load_outlets(["phase_1"])}
    ghost = {r.outlet_slug for r in RATINGS if r.source == "MBFC"} - yaml_slugs
    assert not ghost, (
        f"RATINGS references outlet slug(s) not in phase_1: {sorted(ghost)}"
    )


@pytest.mark.parametrize(
    ("slug", "expected_label", "expected_category"),
    [(s, lbl, cat) for s, (lbl, cat) in EXPECTED_MBFC_PHASE_1.items()],
)
def test_each_phase_1_rating_matches_expected_mapping(
    slug: str, expected_label: str, expected_category: str,
):
    """Every phase_1 outlet's stored MBFC rating and its
    normalisation must match the researched-and-verified value in
    EXPECTED_MBFC_PHASE_1. If MBFC updates a rating, this test fails
    and forces a deliberate update to both RATINGS and the expected
    map — the change never happens silently."""
    matching = [
        r for r in RATINGS
        if r.source == "MBFC" and r.outlet_slug == slug
    ]
    assert len(matching) == 1, (
        f"expected exactly one MBFC rating for {slug!r}, got {len(matching)}"
    )
    rec = matching[0]
    assert rec.original_label == expected_label, (
        f"{slug}: stored label {rec.original_label!r} != "
        f"expected {expected_label!r}"
    )
    normalized = normalize_label(rec.source, rec.original_label)
    assert normalized == expected_category, (
        f"{slug}: label {rec.original_label!r} normalises to "
        f"{normalized!r}, expected {expected_category!r}"
    )
    # URL sanity — every rating must carry a real MBFC link so the
    # source is verifiable in the UI's rating-provenance drawer.
    assert rec.rating_url.startswith("https://mediabiasfactcheck.com/"), (
        f"{slug}: rating_url {rec.rating_url!r} is not on MBFC"
    )


def test_ratings_are_deduplicated_per_source_and_slug():
    """(source, outlet_slug) is the effective uniqueness key — the
    outlet_bias_ratings table has ``ux_outlet_bias_ratings_outlet_source``
    UNIQUE on (outlet_id, source), so any dup in RATINGS would cause
    seed to churn (insert + update the same row within one run)."""
    from collections import Counter
    key_counts = Counter((r.source, r.outlet_slug) for r in RATINGS)
    dupes = [k for k, c in key_counts.items() if c > 1]
    assert not dupes, f"duplicate (source, slug) entries in RATINGS: {dupes}"


# =============================================================================
# Eligibility — spec tests 1, 2, 3, 4
# =============================================================================

def test_two_outlets_is_ineligible():
    """Spec test 1: story with 2 outlets → bar ineligible."""
    outlets = [_outlet(1, "a"), _outlet(2, "b")]
    ratings = [
        _rating(1, "a", "Left-Center", "left"),
        _rating(2, "b", "Right-Center", "right"),
    ]
    r = compute_bias_distribution(outlets, ratings)
    assert r.eligible is False
    assert r.reason == "too_few_outlets"
    assert r.total_outlet_count == 2
    assert r.rated_outlet_count == 0  # short-circuit; we don't count ratings
    assert r.sources == ()


def test_three_outlets_three_rated_is_eligible():
    """Spec test 2: story with 3 outlets and 3 rated → eligible."""
    outlets = [_outlet(1, "a"), _outlet(2, "b"), _outlet(3, "c")]
    ratings = [
        _rating(1, "a", "Left-Center", "left"),
        _rating(2, "b", "Least Biased", "center"),
        _rating(3, "c", "Right-Center", "right"),
    ]
    r = compute_bias_distribution(outlets, ratings)
    assert r.eligible is True
    assert r.reason is None
    assert r.total_outlet_count == 3
    assert r.rated_outlet_count == 3
    assert r.unrated_outlet_count == 0
    assert r.counts == {"left": 1, "center": 1, "right": 1}
    # Each category is 33.33% (with 0.01 rounding tolerance).
    for cat in ("left", "center", "right"):
        assert r.distribution[cat] == pytest.approx(33.33, abs=0.01)


def test_five_outlets_three_rated_two_unrated_is_eligible():
    """Spec test 3: 5 outlets, 3 rated + 2 unrated → eligible; only
    rated outlets contribute to the distribution."""
    outlets = [_outlet(i, f"o{i}") for i in range(1, 6)]
    ratings = [
        _rating(1, "o1", "Left-Center", "left"),
        _rating(2, "o2", "Right-Center", "right"),
        _rating(3, "o3", "Right-Center", "right"),
        # o4 and o5 have no rating rows.
    ]
    r = compute_bias_distribution(outlets, ratings)
    assert r.eligible is True
    assert r.total_outlet_count == 5
    assert r.rated_outlet_count == 3
    assert r.unrated_outlet_count == 2
    assert set(r.unrated_outlet_slugs) == {"o4", "o5"}
    # Distribution uses ONLY the rated ones — 1L / 2R.
    assert r.counts == {"left": 1, "center": 0, "right": 2}
    assert r.distribution["left"]  == pytest.approx(33.33, abs=0.01)
    assert r.distribution["right"] == pytest.approx(66.67, abs=0.01)
    assert r.distribution["center"] == 0.0


def test_five_outlets_only_two_rated_is_ineligible():
    """Spec test 4: 5 outlets, 2 rated + 3 unrated → ineligible;
    'insufficient rated-source coverage'."""
    outlets = [_outlet(i, f"o{i}") for i in range(1, 6)]
    ratings = [
        _rating(1, "o1", "Left-Center", "left"),
        _rating(2, "o2", "Right-Center", "right"),
    ]
    r = compute_bias_distribution(outlets, ratings)
    assert r.eligible is False
    assert r.reason == "too_few_rated_outlets"
    assert r.total_outlet_count == 5
    assert r.rated_outlet_count == 2
    assert r.unrated_outlet_count == 3
    assert r.sources == ()


# =============================================================================
# Distinct-outlet counting — spec test 5 + "same outlet many articles"
# =============================================================================

def test_distribution_uses_distinct_outlets_not_article_count():
    """Spec test 5: an outlet with many articles is counted once.

    The API route dedupes at the SQL level; compute_bias_distribution
    also dedupes defensively on ``id``. This test drives the dedupe by
    passing the same outlet twice in the iterable.
    """
    outlets_iter = [
        _outlet(1, "a"),
        _outlet(1, "a"),   # duplicate — should not count twice
        _outlet(2, "b"),
        _outlet(2, "b"),   # duplicate
        _outlet(3, "c"),
    ]
    ratings = [
        _rating(1, "a", "Left-Center", "left"),
        _rating(2, "b", "Right-Center", "right"),
        _rating(3, "c", "Right-Center", "right"),
    ]
    r = compute_bias_distribution(outlets_iter, ratings)
    assert r.total_outlet_count == 3      # not 5
    assert r.rated_outlet_count == 3
    assert r.counts == {"left": 1, "center": 0, "right": 2}


# =============================================================================
# Unrated outlet remains unrated — spec test 7
# =============================================================================

def test_unrated_outlet_stays_unrated():
    """An outlet without a rating row never gets an implicit category."""
    outlets = [_outlet(1, "a"), _outlet(2, "b"), _outlet(3, "c"), _outlet(4, "d")]
    ratings = [
        _rating(1, "a", "Left-Center", "left"),
        _rating(2, "b", "Least Biased", "center"),
        _rating(3, "c", "Right-Center", "right"),
        # Outlet 4 has no rating.
    ]
    r = compute_bias_distribution(outlets, ratings)
    assert r.eligible is True
    assert "d" in r.unrated_outlet_slugs
    # Sources view is only rated outlets — outlet 4 must not appear.
    assert all(s.outlet_slug != "d" for s in r.sources)
    # No category was silently incremented for the unrated outlet.
    assert sum(r.counts.values()) == 3


def test_rating_with_unmappable_label_treats_outlet_as_unrated():
    """If a stored row's label doesn't map today (e.g. mapping was
    tightened after the row was written), the outlet is unrated — no
    forced category."""
    outlets = [_outlet(1, "a"), _outlet(2, "b"), _outlet(3, "c"), _outlet(4, "d")]
    ratings = [
        _rating(1, "a", "Left-Center", "left"),
        _rating(2, "b", "Right-Center", "right"),
        _rating(3, "c", "Right-Center", "right"),
        # Unmappable label for outlet 4 (source has no such mapping):
        OutletRatingRow(
            outlet_id=4, outlet_slug="d", outlet_name="d",
            source="MBFC", original_label="Extremely Purple",
            normalized_category=None,
            rating_url="https://example/d",
            rated_at=None,
        ),
    ]
    r = compute_bias_distribution(outlets, ratings)
    assert r.rated_outlet_count == 3
    assert r.unrated_outlet_count == 1
    assert "d" in r.unrated_outlet_slugs


# =============================================================================
# Source priority
# =============================================================================

def test_source_priority_selects_higher_priority_source_when_both_present():
    """When two sources rate the same outlet, the one earlier in
    SOURCE_PRIORITY wins — the choice is deterministic, not by rowid."""
    outlets = [_outlet(1, "a"), _outlet(2, "b"), _outlet(3, "c")]
    # Give outlet 1 two ratings from different sources. MBFC is first
    # in SOURCE_PRIORITY, so its Left-Center should win over a
    # hypothetical AdFontes 'Right' rating on the same outlet.
    ratings = [
        _rating(1, "a", "Right",        "right", source="AdFontes"),
        _rating(1, "a", "Left-Center",  "left",  source="MBFC"),
        _rating(2, "b", "Least Biased", "center"),
        _rating(3, "c", "Right-Center", "right"),
    ]
    r = compute_bias_distribution(outlets, ratings)
    # If MBFC won, outlet 1 is left; if AdFontes won, it's right.
    assert r.counts["left"] == 1
    # Sources view carries the winning source name.
    outlet_1_row = next(s for s in r.sources if s.outlet_slug == "a")
    assert outlet_1_row.rating_source == "MBFC"
    assert outlet_1_row.original_rating == "Left-Center"


def test_source_not_in_priority_is_ignored():
    """A rating from a source we don't yet trust is dropped — not
    silently blended into the distribution."""
    outlets = [_outlet(1, "a"), _outlet(2, "b"), _outlet(3, "c")]
    ratings = [
        _rating(1, "a", "Left-Center", "left", source="Randos R Us"),
        _rating(2, "b", "Right-Center", "right"),
        _rating(3, "c", "Right-Center", "right"),
    ]
    r = compute_bias_distribution(outlets, ratings)
    # Only 2 outlets have a source-in-priority rating → ineligible.
    assert r.eligible is False
    assert r.reason == "too_few_rated_outlets"


# =============================================================================
# Ratings whose outlet isn't in the story
# =============================================================================

def test_ratings_for_outlets_not_in_story_are_ignored():
    """Feeding an unrelated outlet's rating row must not contaminate
    the distribution."""
    outlets = [_outlet(1, "a"), _outlet(2, "b"), _outlet(3, "c")]
    ratings = [
        _rating(1, "a", "Left-Center", "left"),
        _rating(2, "b", "Least Biased", "center"),
        _rating(3, "c", "Right-Center", "right"),
        _rating(99, "unrelated", "Right", "right"),
    ]
    r = compute_bias_distribution(outlets, ratings)
    assert r.rated_outlet_count == 3
    assert r.counts == {"left": 1, "center": 1, "right": 1}
    assert all(s.outlet_slug != "unrelated" for s in r.sources)


# =============================================================================
# Sources list ordering
# =============================================================================

def test_sources_are_ordered_left_center_right_then_by_name():
    outlets = [
        _outlet(1, "z-right", name="Z Right"),
        _outlet(2, "a-left",  name="A Left"),
        _outlet(3, "b-center", name="B Center"),
        _outlet(4, "y-left",  name="Y Left"),
    ]
    ratings = [
        _rating(1, "z-right",  "Right-Center", "right", name="Z Right"),
        _rating(2, "a-left",   "Left-Center",  "left",  name="A Left"),
        _rating(3, "b-center", "Least Biased", "center", name="B Center"),
        _rating(4, "y-left",   "Left-Center",  "left",  name="Y Left"),
    ]
    r = compute_bias_distribution(outlets, ratings)
    order = [(s.normalized_category, s.outlet_name) for s in r.sources]
    assert order == [
        ("left",   "A Left"),
        ("left",   "Y Left"),
        ("center", "B Center"),
        ("right",  "Z Right"),
    ]


# =============================================================================
# Sources view preserves provenance
# =============================================================================

def test_sources_view_preserves_original_label_and_url():
    """The API's per-outlet source view must expose the raw label +
    the source URL, verbatim."""
    outlets = [_outlet(1, "a"), _outlet(2, "b"), _outlet(3, "c")]
    ratings = [
        OutletRatingRow(
            outlet_id=1, outlet_slug="a", outlet_name="A",
            source="MBFC", original_label="Left-Center",
            normalized_category="left",
            rating_url="https://mediabiasfactcheck.com/a/",
            rated_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        ),
        _rating(2, "b", "Least Biased", "center"),
        _rating(3, "c", "Right-Center", "right"),
    ]
    r = compute_bias_distribution(outlets, ratings)
    a_row = next(s for s in r.sources if s.outlet_slug == "a")
    assert a_row.original_rating == "Left-Center"
    assert a_row.rating_url == "https://mediabiasfactcheck.com/a/"
    assert a_row.rating_source == "MBFC"
    assert a_row.rated_at == datetime(2024, 5, 1, tzinfo=timezone.utc)


# =============================================================================
# Empty inputs
# =============================================================================

def test_empty_story_is_ineligible_not_a_crash():
    r = compute_bias_distribution([], [])
    assert r.eligible is False
    assert r.reason == "too_few_outlets"
    assert r.total_outlet_count == 0
    assert r.rated_outlet_count == 0
    assert r.sources == ()
    assert r.distribution == {"left": 0.0, "center": 0.0, "right": 0.0}
