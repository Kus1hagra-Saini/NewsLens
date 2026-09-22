"""Pydantic response schema for LLM enrichment.

Validates the JSON returned by the enrichment LLM BEFORE it hits the
database. Range constraints mirror the CHECK constraints on
`article_analysis` (see initial migration and architecture §5, §9), so
an out-of-range LLM value is a clean pydantic.ValidationError inside
`enrich.py`, not a Postgres IntegrityError at INSERT time.

Kept minimal: it validates STRUCTURE and RANGES only. It does NOT
enforce semantic consistency such as "framing_label matches
framing_score" — those consistency rules live in the prompt itself
(prompts/enrich_v1.txt) so they remain reproducible per prompt version.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Enum literals mirror the article_analysis CHECK constraints.
FramingLabel = Literal[
    "critical", "neutral", "supportive", "mixed", "insufficient"
]
QuoteStance = Literal["supports", "criticizes", "neutral", "unclear"]


class Entities(BaseModel):
    """Named entities extracted from the article."""

    model_config = ConfigDict(extra="forbid")

    people:        list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    locations:     list[str] = Field(default_factory=list)
    other:         list[str] = Field(default_factory=list)


class QuotedSource(BaseModel):
    """One directly-quoted source from the article."""

    model_config = ConfigDict(extra="forbid")

    speaker:     str
    affiliation: str | None = None
    quote:       str
    stance:      QuoteStance


class SourceDistribution(BaseModel):
    """Counts of quoted_sources by category. Sum should equal len(quoted_sources)."""

    model_config = ConfigDict(extra="forbid")

    government:     int = Field(default=0, ge=0)
    opposition:     int = Field(default=0, ge=0)
    expert:         int = Field(default=0, ge=0)
    civil_society:  int = Field(default=0, ge=0)
    corporate:      int = Field(default=0, ge=0)
    unnamed_source: int = Field(default=0, ge=0)
    other:          int = Field(default=0, ge=0)


class EnrichmentResponse(BaseModel):
    """The full enrichment response the LLM must produce.

    Field ranges mirror article_analysis CHECK constraints:
      framing_score:      [-1.0, 1.0]
      framing_confidence: [ 0.0, 1.0]
      headline_sentiment: [-1.0, 1.0]
      body_sentiment:     [-1.0, 1.0]
      framing_label:      critical|neutral|supportive|mixed|insufficient
    """

    model_config = ConfigDict(extra="forbid")

    framing_score:       float = Field(ge=-1.0, le=1.0)
    framing_label:       FramingLabel
    framing_confidence:  float = Field(ge=0.0,  le=1.0)
    headline_sentiment:  float = Field(ge=-1.0, le=1.0)
    body_sentiment:      float = Field(ge=-1.0, le=1.0)
    key_themes:          list[str] = Field(default_factory=list)
    entities:            Entities
    quoted_sources:      list[QuotedSource] = Field(default_factory=list)
    source_distribution: SourceDistribution
    evidence_snippets:   list[str] = Field(default_factory=list)
