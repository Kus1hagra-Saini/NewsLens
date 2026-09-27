"""Story-level image selection — deterministic count rule + de-dup.

Pure functions. The API layer feeds in the list of articles and
receives a hero URL plus an ordered list of additional images.
No HTTP, no ORM, no config.

The count rule is fixed by the design brief:

    Articles in story   Max images
    ------------------  ----------
    2 – 6               1
    7 – 10              2
    11+                 3

These are maximums, not requirements. If fewer usable images exist,
fewer are returned. Placeholders are never fabricated to hit the
count. Duplicate URLs are collapsed. Images are selected from
different outlets where possible so a story doesn't visually reduce
to one outlet's photography.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ArticleImageCandidate:
    """One (article, outlet, image URL) triple to feed the selector."""
    article_id: int
    outlet_slug: str
    outlet_name: str
    image_url: str
    published_at_ts: float   # for tie-breaking (newer first)


@dataclass(frozen=True)
class StoryImage:
    """One selected image; ordered by preference (hero first)."""
    url: str
    article_id: int
    outlet_slug: str
    outlet_name: str


# ---------------------------------------------------------------------------
# Count rule
# ---------------------------------------------------------------------------

def max_images_for_article_count(count: int) -> int:
    """Deterministic image cap per the design brief.

    Stories with 0 or 1 articles never show images. This mirrors the
    absence of any "compare across outlets" story of that shape.
    """
    if count < 2:
        return 0
    if count <= 6:
        return 1
    if count <= 10:
        return 2
    return 3


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def select_story_images(
    candidates: Iterable[ArticleImageCandidate],
    total_article_count: int,
) -> list[StoryImage]:
    """Choose up to ``max_images_for_article_count(total_article_count)``
    images from the given candidates.

    Rules baked in:
      - Deduplicate on the exact image URL. Two articles from the same
        outlet syndicating the same photo count as one.
      - Prefer diversity of outlets. Take one image per outlet before
        allowing a second image from any outlet.
      - Within an outlet's turn, prefer the newest article's image.
      - Cap the total at the count-rule maximum for the story.

    Returns an empty list when the story is too small to show images
    or when no usable candidates were provided. Never invents URLs.
    """
    max_n = max_images_for_article_count(total_article_count)
    if max_n <= 0:
        return []

    # Bucket candidates by outlet, drop empty URLs, keep newest first
    # inside each outlet.
    per_outlet: dict[str, list[ArticleImageCandidate]] = {}
    for c in candidates:
        if not isinstance(c.image_url, str) or not c.image_url.strip():
            continue
        per_outlet.setdefault(c.outlet_slug, []).append(c)
    for slug, xs in per_outlet.items():
        xs.sort(key=lambda x: (-x.published_at_ts, x.article_id))

    # Round-robin across outlets so no single outlet dominates.
    # Outlet ordering: the outlet with the newest image goes first,
    # then the next-newest, etc. Deterministic given the same input.
    outlets_ordered = sorted(
        per_outlet.keys(),
        key=lambda slug: (
            -max((x.published_at_ts for x in per_outlet[slug]), default=0.0),
            slug,
        ),
    )

    seen_urls: set[str] = set()
    picked: list[StoryImage] = []

    round_idx = 0
    while len(picked) < max_n:
        added_this_round = 0
        for slug in outlets_ordered:
            if len(picked) >= max_n:
                break
            bucket = per_outlet[slug]
            if round_idx >= len(bucket):
                continue
            c = bucket[round_idx]
            if c.image_url in seen_urls:
                continue
            seen_urls.add(c.image_url)
            picked.append(StoryImage(
                url=c.image_url,
                article_id=c.article_id,
                outlet_slug=c.outlet_slug,
                outlet_name=c.outlet_name,
            ))
            added_this_round += 1
        if added_this_round == 0:
            # No new URL fits in this round → no point looping more.
            break
        round_idx += 1

    return picked


def hero_image_from_selection(images: list[StoryImage]) -> str | None:
    """The first selected image is the hero, if any."""
    return images[0].url if images else None
