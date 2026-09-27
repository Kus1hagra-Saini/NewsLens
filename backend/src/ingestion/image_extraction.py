"""Article-image URL extractors.

NewsLens never downloads or rehosts images. This module returns
absolute URLs (as strings) that can be stored verbatim in
``articles.image_url``; the frontend loads the images directly from
the outlet.

Three extractors, in the documented priority order:

  1. ``image_url_from_feed_entry(entry)`` — mines an already-parsed
     feedparser entry for ``media:content``, ``media:thumbnail``, a
     legacy ``<enclosure>`` element, or an ``<image>`` child.
  2. ``image_url_from_html(html, base_url)`` — parses HTML and returns
     the first usable ``og:image`` or ``twitter:image`` value.

Both pass their candidates through ``normalise_and_validate`` which
absolutises relative URLs, drops fragments, and rejects likely
non-content assets (tracking pixels, logos, tiny thumbnails, blank
strings, non-``http(s)`` schemes).

Everything is pure Python and side-effect free — the module never
opens a socket. Callers own the HTTP request; this module only
interprets the bytes.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse


# ---------------------------------------------------------------------------
# URL normalisation + validation
# ---------------------------------------------------------------------------

# File extensions we consider image content. A URL without an
# extension is not disqualified (many CDNs strip the extension), but
# a URL with one of these is a strong positive signal.
_IMAGE_EXTENSIONS: tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif",
)

# Substrings that strongly suggest the URL points at a
# non-editorial asset. Case-insensitive substring match.
_BAD_URL_SUBSTRINGS: tuple[str, ...] = (
    "logo",
    "sprite",
    "favicon",
    "placeholder",
    "default-",
    "pixel",
    "1x1",
    "spacer",
    "beacon",
    "tracker",
    "tracking",
    "advert",
    "google-analytics",
    "doubleclick",
    "/ads/",
    "/ad-",
    "-ad.",
    "amazon-adsystem",
)

# Query-parameter names whose numeric value indicates the image
# dimension. If BOTH width and height fall below the minimum, we
# treat the URL as a thumbnail and reject it. Example:
# https://example.com/img.jpg?w=32&h=32 → tiny.
_WIDTH_PARAM_NAMES: tuple[str, ...] = ("w", "width")
_HEIGHT_PARAM_NAMES: tuple[str, ...] = ("h", "height")

# Below this in EITHER stated dimension the URL is treated as a
# thumbnail. Chosen conservatively — real hero images are >= 480px.
_MIN_STATED_DIMENSION = 200


def normalise_and_validate(url: str | None, *, base_url: str | None = None) -> str | None:
    """Turn a candidate URL into a validated, absolute ``str`` or None.

    - Trims whitespace and quotes.
    - Absolutises relative paths against ``base_url`` when provided.
    - Rejects non-``http(s)`` schemes (``data:`` URIs, ``javascript:``
      links, missing scheme with no base).
    - Rejects strings that match the bad-substring list above.
    - Rejects URLs whose declared dimensions (via query string) are
      obvious thumbnails.
    - Strips URL fragments (``#foo``) which are meaningless for images.
    """
    if not isinstance(url, str):
        return None
    candidate = url.strip().strip('"').strip("'")
    if not candidate:
        return None

    # Absolutise
    if base_url:
        candidate = urljoin(base_url, candidate)

    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.netloc:
        return None

    # Rebuild without fragment.
    absolute = parsed._replace(fragment="").geturl()

    lowered = absolute.lower()
    for bad in _BAD_URL_SUBSTRINGS:
        if bad in lowered:
            return None

    # Query-string dimension check. Only rejects when BOTH dims are
    # tiny — a single tiny dim can be a legitimate CDN cropping param.
    stated_w = _int_query_param(parsed.query, _WIDTH_PARAM_NAMES)
    stated_h = _int_query_param(parsed.query, _HEIGHT_PARAM_NAMES)
    if (
        stated_w is not None and stated_h is not None
        and stated_w < _MIN_STATED_DIMENSION
        and stated_h < _MIN_STATED_DIMENSION
    ):
        return None

    return absolute


def _int_query_param(query: str, names: Iterable[str]) -> int | None:
    """Best-effort read of a numeric query param by any of ``names``.

    Handles simple ``a=1&b=2`` shapes; ignores repeats and malformed
    pieces. Returns None when the param is absent or not an int.
    """
    if not query:
        return None
    for chunk in query.split("&"):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        if k.lower() in names:
            try:
                return int(v)
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# RSS / feedparser entry extractor
# ---------------------------------------------------------------------------

def image_url_from_feed_entry(entry: Any, *, base_url: str | None = None) -> str | None:
    """Return the best image URL on a feedparser entry, or None.

    Order of preference:
      1. ``media_content`` items with a matching ``medium`` value or a
         plausible image URL.
      2. ``media_thumbnail`` entries.
      3. ``enclosures`` where the MIME type starts with ``image/``.
      4. ``links`` where ``rel`` is enclosure and the type starts image/
      5. A single ``image`` mapping (some RSS 2.0 feeds).
      6. An inline ``<img src="…">`` in ``content`` or ``summary`` HTML.

    The chosen URL passes through ``normalise_and_validate`` so
    non-image assets (tracker pixels, logos, tiny thumbs) are filtered
    out and relative paths are absolutised against ``base_url`` when
    supplied (feed entries occasionally carry root-relative URLs).
    """
    if entry is None:
        return None

    for candidate in _iter_feed_candidates(entry):
        cleaned = normalise_and_validate(candidate, base_url=base_url)
        if cleaned:
            return cleaned
    return None


def _iter_feed_candidates(entry: Any) -> Iterable[str]:
    # 1. media:content — a list of dicts with 'url', 'type', 'medium'.
    media = _get(entry, "media_content", [])
    if isinstance(media, list):
        for m in media:
            if not isinstance(m, dict):
                continue
            medium = str(m.get("medium", "")).lower()
            mime = str(m.get("type", "")).lower()
            if medium == "image" or mime.startswith("image/"):
                if m.get("url"):
                    yield str(m["url"])
            elif not medium and not mime and m.get("url"):
                # Some feeds omit the medium; fall back to the URL if
                # it obviously looks like an image extension.
                url = str(m["url"])
                if _looks_like_image_url(url):
                    yield url

    # 2. media:thumbnail
    thumbs = _get(entry, "media_thumbnail", [])
    if isinstance(thumbs, list):
        for t in thumbs:
            if isinstance(t, dict) and t.get("url"):
                yield str(t["url"])

    # 3. enclosures
    encl = _get(entry, "enclosures", [])
    if isinstance(encl, list):
        for e in encl:
            if not isinstance(e, dict):
                continue
            mime = str(e.get("type", "")).lower()
            href = e.get("href") or e.get("url")
            if href and (mime.startswith("image/") or _looks_like_image_url(str(href))):
                yield str(href)

    # 4. rel=enclosure inside links
    links = _get(entry, "links", [])
    if isinstance(links, list):
        for l in links:
            if not isinstance(l, dict):
                continue
            if str(l.get("rel", "")).lower() != "enclosure":
                continue
            mime = str(l.get("type", "")).lower()
            href = l.get("href")
            if href and (mime.startswith("image/") or _looks_like_image_url(str(href))):
                yield str(href)

    # 5. single 'image' mapping (rare on Atom, common on some RSS)
    image = _get(entry, "image", None)
    if isinstance(image, dict) and image.get("href"):
        yield str(image["href"])
    elif isinstance(image, str) and image.strip():
        yield image.strip()

    # 6. inline <img> in content:encoded / summary — last resort.
    for key in ("content", "summary_detail", "summary"):
        val = _get(entry, key, None)
        if val is None:
            continue
        if isinstance(val, list):
            html_blobs = [str(x.get("value", "")) for x in val if isinstance(x, dict)]
        elif isinstance(val, dict):
            html_blobs = [str(val.get("value", ""))]
        elif isinstance(val, str):
            html_blobs = [val]
        else:
            html_blobs = []
        for html in html_blobs:
            m = _INLINE_IMG_RE.search(html)
            if m:
                yield m.group(1).strip()


_INLINE_IMG_RE = re.compile(
    r'<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _looks_like_image_url(url: str) -> bool:
    lowered = url.lower().split("?", 1)[0]
    return any(lowered.endswith(ext) for ext in _IMAGE_EXTENSIONS)


def _get(entry: Any, key: str, default: Any) -> Any:
    """feedparser entries are FeedParserDict but also support .get()."""
    getter = getattr(entry, "get", None)
    if getter is None:
        return default
    try:
        return getter(key, default)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# HTML og:image / twitter:image extractor
# ---------------------------------------------------------------------------

# Only look at meta tags in the head; we short-circuit at </head> or
# after the first hit for each name. Case-insensitive attribute names
# because real-world HTML is inconsistent.
class _MetaImageParser(HTMLParser):
    """Collects candidate image URLs from <meta> tags in a single pass.

    Deliberately tolerant of malformed HTML. Halts at </head> or after
    it has both an og:image AND a twitter:image so we don't parse the
    whole body of a large article page for two tags.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_image: str | None = None
        self.twitter_image: str | None = None
        self._in_head = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        # og:image — canonical Open Graph tag.
        prop = attr_map.get("property", "").strip().lower()
        name = attr_map.get("name", "").strip().lower()
        content = attr_map.get("content", "").strip()

        if not content:
            return
        if prop in ("og:image", "og:image:url", "og:image:secure_url"):
            if self.og_image is None:
                self.og_image = content
        elif name in ("og:image", "og:image:url"):
            if self.og_image is None:
                self.og_image = content
        elif prop in ("twitter:image", "twitter:image:src"):
            if self.twitter_image is None:
                self.twitter_image = content
        elif name in ("twitter:image", "twitter:image:src"):
            if self.twitter_image is None:
                self.twitter_image = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "head":
            self._in_head = False
            # Stop parsing early — feed the parser an empty buffer.
            raise _StopParsing()


class _StopParsing(Exception):
    """Sentinel to short-circuit HTMLParser once </head> is seen."""


def image_url_from_html(html: str | None, *, base_url: str | None = None) -> str | None:
    """Return og:image (preferred) or twitter:image from the HTML, or None."""
    if not html:
        return None

    p = _MetaImageParser()
    try:
        p.feed(html)
        p.close()
    except _StopParsing:
        pass  # normal early-exit at </head>
    except Exception:
        # Any HTML parsing error is a soft failure — never blocks
        # article ingestion, per the design brief.
        pass

    for candidate in (p.og_image, p.twitter_image):
        cleaned = normalise_and_validate(candidate, base_url=base_url)
        if cleaned:
            return cleaned
    return None
