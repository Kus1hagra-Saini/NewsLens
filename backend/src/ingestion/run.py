"""Ingestion orchestrator.

Entry point invoked by GitHub Actions cron (§14) and by
`python -m src.ingestion.run --once` locally (§16). Opens an
ingestion_runs row, walks each stage, records counts, closes the row with
a terminal status. Full implementation lands in Week 1, step 6.
"""

def main() -> None:
    """Run one ingestion cycle. Body added in step 6."""
    raise NotImplementedError("Populated in Week 1, step 6.")


if __name__ == "__main__":
    main()
