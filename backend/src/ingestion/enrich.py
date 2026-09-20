"""Per-article LLM enrichment (framing, sentiment, entities, themes, quotes).

Uses prompts/enrich_v1.txt; every call records an analysis_runs row.
Advances rows from `clustered` to `analyzed` (or `failed_analyze` after
attempt_count exceeds the 3-failure limit). Implemented in Week 2.
"""
