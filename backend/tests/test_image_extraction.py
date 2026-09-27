"""Unit tests for image_extraction + story_images.

All pure Python — no DB, no HTTP. Exercises every extractor path,
the story-level count rule, deduplication, outlet diversity, and the
backfill's fault-tolerance.

The API-shape integration (image_url on ArticleInStory,
hero_image_url + story_images on StoryDetail) is exercised in
test_api.py alongside the existing bias-distribution shape test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import feedparser
import pytest

from src.analysis.story_images import (
    ArticleImageCandidate,
    hero_image_from_selection,
    max_images_for_article_count,
    select_story_images,
)
from src.ingestion.image_extraction import (
    image_url_from_feed_entry,
    image_url_from_html,
    normalise_and_validate,
)


# =============================================================================
# normalise_and_validate
# =============================================================================

def test_normalise_absolute_https_url_returns_verbatim():
    u = "https://example.com/photo.jpg"
    assert normalise_and_validate(u) == u


def test_normalise_absolutises_relative_against_base():
    got = normalise_and_validate(
        "/img/hero.jpg", base_url="https://example.com/story/1",
    )
    assert got == "https://example.com/img/hero.jpg"


def test_normalise_strips_fragment():
    assert (
        normalise_and_validate("https://example.com/a.jpg#frag")
        == "https://example.com/a.jpg"
    )


def test_normalise_rejects_data_uri():
    assert normalise_and_validate("data:image/png;base64,iVBOR…") is None


def test_normalise_rejects_javascript_scheme():
    assert normalise_and_validate("javascript:void(0)") is None


def test_normalise_rejects_empty_string():
    assert normalise_and_validate("") is None
    assert normalise_and_validate("   ") is None
    assert normalise_and_validate(None) is None


def test_normalise_rejects_bad_substrings():
    # Every substring in the bad list should get filtered.
    bad = [
        "https://example.com/logo.png",
        "https://example.com/sprite/foo.png",
        "https://example.com/favicon.ico",
        "https://example.com/placeholder.jpg",
        "https://example.com/default-avatar.png",
        "https://example.com/pixel.gif",
        "https://example.com/1x1.gif",
        "https://example.com/spacer.gif",
        "https://example.com/beacon.gif",
        "https://example.com/tracker.png",
        "https://example.com/advert-banner.jpg",
        "https://www.google-analytics.com/collect.gif",
        "https://ad.doubleclick.net/foo.png",
        "https://example.com/ads/banner.png",
        "https://example.com/ad-slot.png",
        "https://example.com/banner-ad.png",
        "https://s.amazon-adsystem.com/xyz.png",
    ]
    for u in bad:
        assert normalise_and_validate(u) is None, u


def test_normalise_rejects_tiny_stated_dimensions():
    # Both w and h below the min → reject.
    assert normalise_and_validate(
        "https://example.com/img.jpg?w=32&h=32"
    ) is None


def test_normalise_keeps_url_with_one_large_dim():
    # A single large dim is legitimate (CDN cropping); don't reject.
    assert normalise_and_validate(
        "https://example.com/img.jpg?w=1200&h=100"
    ) == "https://example.com/img.jpg?w=1200&h=100"


# =============================================================================
# RSS / feedparser extractor
# =============================================================================

def _feed_with(item_body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">'
        '<channel><title>t</title>'
        '<item>'
        f'<title>Sample headline</title>'
        f'<link>https://example.com/story-1</link>'
        f'<pubDate>Mon, 27 Sep 2026 12:00:00 +0000</pubDate>'
        f'{item_body}'
        '</item>'
        '</channel></rss>'
    )


def _first_entry(rss: str):
    parsed = feedparser.parse(rss)
    assert parsed.entries, "test feed produced no entries"
    return parsed.entries[0]


def test_rss_media_content_wins():
    rss = _feed_with(
        '<media:content url="https://example.com/hero.jpg" medium="image" />'
    )
    got = image_url_from_feed_entry(_first_entry(rss))
    assert got == "https://example.com/hero.jpg"


def test_rss_media_thumbnail_when_no_media_content():
    rss = _feed_with(
        '<media:thumbnail url="https://example.com/thumb.jpg" />'
    )
    got = image_url_from_feed_entry(_first_entry(rss))
    assert got == "https://example.com/thumb.jpg"


def test_rss_enclosure_image_type():
    rss = _feed_with(
        '<enclosure url="https://example.com/pic.jpg" '
        'length="1234" type="image/jpeg" />'
    )
    got = image_url_from_feed_entry(_first_entry(rss))
    assert got == "https://example.com/pic.jpg"


def test_rss_inline_img_in_description_as_fallback():
    rss = _feed_with(
        "<description>"
        "&lt;p&gt;Story text here.&lt;/p&gt; "
        '&lt;img src="https://example.com/inline.jpg" /&gt;'
        "</description>"
    )
    got = image_url_from_feed_entry(_first_entry(rss))
    assert got == "https://example.com/inline.jpg"


def test_rss_no_image_returns_none():
    rss = _feed_with("")
    assert image_url_from_feed_entry(_first_entry(rss)) is None


def test_rss_prefers_media_content_over_thumbnail_and_inline():
    rss = _feed_with(
        '<media:content url="https://example.com/hero.jpg" medium="image" />'
        '<media:thumbnail url="https://example.com/thumb.jpg" />'
        "<description>"
        '&lt;img src="https://example.com/inline.jpg" /&gt;'
        "</description>"
    )
    got = image_url_from_feed_entry(_first_entry(rss))
    assert got == "https://example.com/hero.jpg"


def test_rss_filters_out_logo_url():
    rss = _feed_with(
        '<media:content url="https://example.com/logo.png" medium="image" />'
    )
    assert image_url_from_feed_entry(_first_entry(rss)) is None


# =============================================================================
# HTML og:image / twitter:image
# =============================================================================

def _html_with_meta(*metas: str) -> str:
    return (
        "<html><head><title>t</title>"
        + "".join(metas)
        + "</head><body><p>body</p></body></html>"
    )


def test_html_og_image_wins():
    html = _html_with_meta(
        '<meta property="og:image" content="https://example.com/og.jpg" />',
    )
    assert image_url_from_html(html) == "https://example.com/og.jpg"


def test_html_twitter_image_as_fallback():
    html = _html_with_meta(
        '<meta name="twitter:image" content="https://example.com/tw.jpg" />',
    )
    assert image_url_from_html(html) == "https://example.com/tw.jpg"


def test_html_prefers_og_over_twitter():
    html = _html_with_meta(
        '<meta property="og:image" content="https://example.com/og.jpg" />',
        '<meta name="twitter:image" content="https://example.com/tw.jpg" />',
    )
    assert image_url_from_html(html) == "https://example.com/og.jpg"


def test_html_relative_og_image_absolutised_against_base():
    html = _html_with_meta(
        '<meta property="og:image" content="/img/hero.jpg" />',
    )
    got = image_url_from_html(html, base_url="https://example.com/a")
    assert got == "https://example.com/img/hero.jpg"


def test_html_missing_meta_returns_none():
    html = "<html><head><title>t</title></head><body>nothing</body></html>"
    assert image_url_from_html(html) is None


def test_html_empty_input_returns_none():
    assert image_url_from_html("") is None
    assert image_url_from_html(None) is None


def test_html_malformed_html_does_not_raise():
    # Deliberately broken markup: unclosed tags, weird attributes.
    html = (
        '<meta property="og:image" content="https://example.com/a.jpg"'
        '<meta name="twitter:image" content="https://example.com/b.jpg" >'
    )
    # Should not throw; may or may not extract, but never raises.
    got = image_url_from_html(html)
    assert got is None or got.startswith("https://")


def test_html_rejects_logo_meta():
    html = _html_with_meta(
        '<meta property="og:image" content="https://example.com/logo.png" />',
    )
    assert image_url_from_html(html) is None


# =============================================================================
# Story-level count rule
# =============================================================================

@pytest.mark.parametrize("count,expected", [
    (0, 0),
    (1, 0),
    (2, 1),
    (3, 1),
    (4, 1),
    (5, 1),
    (6, 1),
    (7, 2),
    (8, 2),
    (9, 2),
    (10, 2),
    (11, 3),
    (25, 3),
    (100, 3),
])
def test_max_images_for_article_count(count, expected):
    assert max_images_for_article_count(count) == expected


# =============================================================================
# select_story_images
# =============================================================================

def _c(article_id, slug, url, days_ago=0):
    return ArticleImageCandidate(
        article_id=article_id,
        outlet_slug=slug,
        outlet_name=slug.title(),
        image_url=url,
        published_at_ts=(datetime.now(tz=timezone.utc)
                         - timedelta(days=days_ago)).timestamp(),
    )


def test_select_none_when_story_too_small():
    picked = select_story_images([_c(1, "a", "https://x/1.jpg")], total_article_count=1)
    assert picked == []


def test_select_one_for_2_to_6_articles():
    cands = [_c(i, f"o{i}", f"https://x/{i}.jpg", days_ago=i) for i in range(1, 6)]
    for n in (2, 3, 4, 5, 6):
        picked = select_story_images(cands, total_article_count=n)
        assert len(picked) == 1


def test_select_two_for_7_to_10_articles():
    cands = [_c(i, f"o{i}", f"https://x/{i}.jpg", days_ago=i) for i in range(1, 6)]
    for n in (7, 8, 9, 10):
        picked = select_story_images(cands, total_article_count=n)
        assert len(picked) == 2


def test_select_three_for_11_plus_articles():
    cands = [_c(i, f"o{i}", f"https://x/{i}.jpg", days_ago=i) for i in range(1, 6)]
    for n in (11, 12, 25):
        picked = select_story_images(cands, total_article_count=n)
        assert len(picked) == 3


def test_select_returns_fewer_when_fewer_usable_images():
    # 12 articles → up to 3 images allowed, but only 1 candidate.
    cands = [_c(1, "a", "https://x/only.jpg")]
    picked = select_story_images(cands, total_article_count=12)
    assert len(picked) == 1
    assert picked[0].url == "https://x/only.jpg"


def test_select_dedupes_exact_urls():
    # Two outlets carrying the same syndicated photo → 1 image.
    cands = [
        _c(1, "a", "https://cdn.example/shared.jpg", days_ago=0),
        _c(2, "b", "https://cdn.example/shared.jpg", days_ago=1),
    ]
    picked = select_story_images(cands, total_article_count=8)
    urls = [p.url for p in picked]
    assert urls == ["https://cdn.example/shared.jpg"]


def test_select_prefers_outlet_diversity_before_second_from_same_outlet():
    # 3-outlet split with plenty of candidates; count rule allows 3 →
    # each of the three outlets should contribute one image.
    cands = [
        _c(1, "a", "https://x/a1.jpg", days_ago=0),
        _c(2, "a", "https://x/a2.jpg", days_ago=1),
        _c(3, "b", "https://x/b1.jpg", days_ago=2),
        _c(4, "c", "https://x/c1.jpg", days_ago=3),
    ]
    picked = select_story_images(cands, total_article_count=11)
    slugs = [p.outlet_slug for p in picked]
    assert sorted(slugs) == ["a", "b", "c"], slugs


def test_select_falls_back_to_second_image_from_same_outlet_when_needed():
    # Only 2 outlets available, but count rule allows 3 → the third
    # comes from whichever outlet has a second unique image.
    cands = [
        _c(1, "a", "https://x/a1.jpg", days_ago=0),
        _c(2, "a", "https://x/a2.jpg", days_ago=1),
        _c(3, "b", "https://x/b1.jpg", days_ago=2),
    ]
    picked = select_story_images(cands, total_article_count=11)
    assert len(picked) == 3
    urls = {p.url for p in picked}
    assert urls == {"https://x/a1.jpg", "https://x/a2.jpg", "https://x/b1.jpg"}


def test_select_ignores_empty_and_whitespace_urls():
    cands = [
        _c(1, "a", "  ", days_ago=0),
        _c(2, "a", "", days_ago=1),
        _c(3, "b", "https://x/b.jpg", days_ago=2),
    ]
    picked = select_story_images(cands, total_article_count=6)
    assert [p.url for p in picked] == ["https://x/b.jpg"]


def test_hero_from_selection_returns_first_url_or_none():
    picked = select_story_images(
        [_c(1, "a", "https://x/a.jpg"), _c(2, "b", "https://x/b.jpg", days_ago=5)],
        total_article_count=3,
    )
    assert hero_image_from_selection(picked) == picked[0].url
    assert hero_image_from_selection([]) is None
