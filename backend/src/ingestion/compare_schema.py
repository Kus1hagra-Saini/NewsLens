"""Pydantic response schema for LLM story comparison.

Validates the JSON returned by the comparison LLM BEFORE persisting to
``story_comparisons``. Mirrors the fields defined in Appendix C of the
architecture and the ``StoryComparison`` model.

Note: ``framing_spread`` is intentionally NOT part of this schema.
`compare.py` computes it deterministically (population std-dev of
``article_analysis.framing_score`` across the story's analyzed
articles) so the LLM cannot introduce arithmetic errors on a value we
can compute exactly. See architecture Appendix C schema comment
("std-dev of framing across outlets").
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ComparisonResponse(BaseModel):
    """The LLM's structured comparison of how outlets covered one story.

    Fields:
      * ``differences``      — non-empty markdown; bullets naming
                               specific outlets.
      * ``coverage_matrix``  — ``{outlet_slug: {theme: emphasis}}``.
                               Emphasis in [0.0, 1.0]. Themes should be
                               exactly the fixed list supplied in the
                               prompt (union of the story's articles'
                               key_themes).
      * ``not_present_here`` — ``{outlet_slug: [facts]}``. Each fact
                               must be present in at least one OTHER
                               outlet's analysis payload (grounding
                               rule; not enforced structurally here —
                               the prompt enforces it).
    """

    model_config = ConfigDict(extra="forbid")

    differences:      str
    coverage_matrix:  dict[str, dict[str, float]] = Field(default_factory=dict)
    not_present_here: dict[str, list[str]]        = Field(default_factory=dict)

    @field_validator("differences")
    @classmethod
    def _differences_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("differences must be non-empty markdown text")
        return v

    @field_validator("coverage_matrix")
    @classmethod
    def _coverage_values_in_range(
        cls,
        v: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        for slug, themes in v.items():
            if not isinstance(themes, dict):
                raise ValueError(
                    f"coverage_matrix[{slug!r}] must be a dict"
                )
            for theme, score in themes.items():
                try:
                    fs = float(score)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"coverage_matrix[{slug!r}][{theme!r}]={score!r} "
                        f"is not a number"
                    ) from exc
                if not (0.0 <= fs <= 1.0):
                    raise ValueError(
                        f"coverage_matrix[{slug!r}][{theme!r}]={fs} "
                        f"out of range [0.0, 1.0]"
                    )
        return v
