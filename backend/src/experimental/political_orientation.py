"""Experimental political-orientation classifier — FLAG-GATED.

This module is intentionally not wired into the pipeline or the dashboard.
NewsLens's public claims are limited to the framing indicator (−1..+1
critical/supportive of the article's primary subject) with confidence and
an evidence bundle. See architecture §5.

Anyone importing this module must (a) do so behind an explicit feature
flag, (b) not surface its output on any user-facing view, and (c) not
introduce dependencies from src.main or src.api.* to this file.
"""

from __future__ import annotations


def classify(*_args, **_kwargs) -> None:
    """Placeholder. Left unimplemented on purpose during the scaffold."""
    raise NotImplementedError(
        "Experimental political-orientation classifier is not implemented "
        "and must not become a primary dashboard feature."
    )
