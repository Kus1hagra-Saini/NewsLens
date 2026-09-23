"""Pydantic v2 response models for the NewsLens HTTP API.

Explicit response models keep API-visible fields separate from ORM
internals: embeddings, full article text (only sent when explicitly
requested), state_error, attempt_count, and other operational columns
never appear in a response unless a schema below spells them out.

Every response that exposes framing information also carries
FRAMING_DISCLAIMER (arch §5) so the frontend never renders a bare
score without the outlet-agnostic caveat.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


FRAMING_DISCLAIMER: str = (
    "NewsLens provides automated framing indicators based on article "
    "content. These describe observed coverage patterns and should not "
    "be interpreted as definitive judgments about an outlet."
)


# ---------------------------------------------------------------------------
# Outlets
# ---------------------------------------------------------------------------
class OutletSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:       int
    name:     str
    slug:     str
    website:  str
    logo_url: str | None = None


class OutletDetail(OutletSummary):
    model_config = ConfigDict(from_attributes=True)
    rss_url: str
    active:  bool


class OutletStats(BaseModel):
    outlet_id:     int
    slug:          str
    name:          str
    article_count: int
    avg_framing:   float | None
    avg_sentiment: float | None
    top_themes:    dict | None
    framing_disclaimer: str = FRAMING_DISCLAIMER


# ---------------------------------------------------------------------------
# Analysis (nested inside articles / stories)
# ---------------------------------------------------------------------------
class ArticleAnalysisPayload(BaseModel):
    framing_score:       float | None
    framing_label:       str   | None
    framing_confidence:  float | None
    headline_sentiment:  float | None
    body_sentiment:      float | None
    key_themes:          list[str]
    entities:            dict
    quoted_sources:      list
    source_distribution: dict | None
    evidence_snippets:   list
    analyzed_at:         datetime


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------
class ArticleInStory(BaseModel):
    """Article view for the story-detail endpoint."""
    id:                int
    outlet:            OutletSummary
    url:               str
    headline:          str
    author:            str | None
    published_at:      datetime
    processing_state:  str
    analysis:          ArticleAnalysisPayload | None


class ArticleDetail(ArticleInStory):
    """Article view for the article-detail endpoint. Adds story_id and
    a `full_text_available` flag (the body itself is NOT returned unless
    explicitly requested via a future ?include=body param — kept out of
    the API contract for now)."""
    story_id:            int | None
    full_text_available: bool


# ---------------------------------------------------------------------------
# Stories
# ---------------------------------------------------------------------------
class StorySummary(BaseModel):
    id:              int
    title:           str
    topic:           str | None
    first_seen_at:   datetime
    last_seen_at:    datetime
    article_count:   int
    summary:         str | None
    outlet_slugs:    list[str]
    framing_spread:  float | None


class StoryComparisonPayload(BaseModel):
    differences:       str
    framing_spread:    float | None
    coverage_matrix:   dict | None
    not_present_here:  dict | None
    generated_at:      datetime


class StoryDetail(StorySummary):
    articles:           list[ArticleInStory]
    comparison:         StoryComparisonPayload | None
    framing_disclaimer: str = FRAMING_DISCLAIMER


class PaginatedStories(BaseModel):
    items: list[StorySummary]
    page:  int
    limit: int
    total: int
    has_more: bool


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class SearchHit(BaseModel):
    article_id:   int
    outlet_slug:  str
    headline:     str
    url:          str
    published_at: datetime
    rank:         float
    snippet:      str


class PaginatedSearch(BaseModel):
    query:    str
    items:    list[SearchHit]
    page:     int
    limit:    int
    total:    int
    has_more: bool


# ---------------------------------------------------------------------------
# Overview / Trends
# ---------------------------------------------------------------------------
class LatestIngestionRun(BaseModel):
    id:                  int
    started_at:          datetime
    completed_at:        datetime | None
    status:              str
    articles_discovered: int
    articles_inserted:   int
    articles_failed:     int
    llm_calls:           int


class DashboardOverview(BaseModel):
    article_count:            int
    story_count:              int
    active_outlet_count:      int
    articles_by_state:        dict[str, int]
    articles_last_24h:        int
    stories_last_24h:         int
    latest_ingestion_run:     LatestIngestionRun | None
    framing_distribution:     dict[str, int]
    framing_disclaimer:       str = FRAMING_DISCLAIMER


class TimeSeriesPoint(BaseModel):
    date:  str    # YYYY-MM-DD (UTC)
    count: int


class FramingBucket(BaseModel):
    label: str
    count: int


class TrendsResponse(BaseModel):
    window_days:           int
    articles_per_day:      list[TimeSeriesPoint]
    stories_per_day:       list[TimeSeriesPoint]
    framing_distribution:  list[FramingBucket]
    framing_disclaimer:    str = FRAMING_DISCLAIMER


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    detail: str
