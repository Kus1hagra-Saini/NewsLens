"""Shared logging setup for the ingestion pipeline."""

from __future__ import annotations

import logging
import os


def setup_logging(level: str | int | None = None) -> None:
    """Configure the root logger for CLI + GitHub Actions.

    Log level defaults to LOG_LEVEL env, else INFO. Format is terse and
    grep-friendly.
    """
    resolved = level if level is not None else os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)-5s %(name)-30s %(message)s",
        datefmt="%H:%M:%S",
    )
