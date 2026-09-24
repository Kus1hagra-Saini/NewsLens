"""Unit tests for the grounding-check normalization helper.

These test ``scripts.enrich_sample._grounding_normalize`` directly.
That helper is USED BY THE VERIFICATION SCRIPT ONLY — it never runs
during production ingestion. It exists so that the sample-run
grounding math (does this snippet appear in the article body?)
tolerates the Unicode variants publishers actually use (curly quotes,
non-breaking hyphens, no-break spaces, thin spaces, etc.) without
falsely flagging a snippet as "hallucinated".

Nothing here writes to the database. Nothing here mutates model
output. Nothing here relaxes the STRICT VERBATIM RULES in enrich_v2:
those are the model's contract, and are checked separately.
"""
from __future__ import annotations

import pytest

from scripts.enrich_sample import _grounding_normalize


def test_grounding_normalize_folds_curly_quotes_and_dashes():
    """Curly quotes, en/em dashes, and non-breaking / narrow spaces in
    the model's output must be recognised as equivalent to their ASCII
    counterparts in the article body."""
    # A common publisher rendering of a quoted phrase:
    #   "It’s vote‑chori," Gandhi said.
    # (curly right-single-quote apostrophe + non-breaking hyphen)
    model_snippet = "It’s vote‑chori"
    body_ascii    = "it's vote-chori is what he called it"

    # Verification-only equivalence: the normalized model snippet is a
    # substring of the normalized body.
    assert _grounding_normalize(model_snippet) in _grounding_normalize(body_ascii)


def test_grounding_normalize_collapses_whitespace_and_lowercases():
    """Runs of whitespace (\\t, \\n, multiple spaces) collapse to one
    space, and the result is lowercased. Idempotent."""
    raw = "  The\tBudget\n  2026   Reform  "
    once = _grounding_normalize(raw)
    twice = _grounding_normalize(once)

    assert once == "the budget 2026 reform"
    assert twice == once, "normalization must be idempotent"


def test_grounding_normalize_handles_nbsp_thin_space_and_zero_width():
    """No-break space (U+00A0), thin space (U+2009), narrow no-break
    space (U+202F), and zero-width space (U+200B) must be folded so a
    snippet copy-pasted from a rendered article page still matches its
    plain-ASCII source in the body."""
    #   "Rs. 2,000 crore" (nbsp between Rs. and 2,000; thin
    #   space between 2,000 and crore)
    model_snippet = "Rs. 2,000 crore"
    #   Body was extracted as plain ASCII spaces.
    body_ascii    = "the government announced rs. 2,000 crore for the scheme"

    # Zero-width space in the middle of the model output must vanish.
    with_zw = "Rs. 2,000​ crore"

    assert _grounding_normalize(model_snippet) in _grounding_normalize(body_ascii)
    assert _grounding_normalize(with_zw) == _grounding_normalize(model_snippet), (
        "zero-width space must be stripped so the two snippets fold identically"
    )
