# NewsLens Architecture

The authoritative locked build contract lives in the project doc
**`NewsLens_Architecture_v2.md`**, attached to the claude.ai Project for this
repository.

This file is intentionally a pointer, not a copy: keeping a second copy
in-repo invites drift. When the architecture doc changes, that change is
mirrored here as a dated note rather than a rewrite.

## Change log

- `2026-09-20` — Week 1 kickoff. Working from `NewsLens_Architecture_v2.md`
  as locked. Implementation corrections agreed with owner (do not treat as
  redesigns):
  - `article_analysis.article_id` remains sole PK (latest-wins).
  - `articles.attempt_count INTEGER NOT NULL DEFAULT 0` added to back the
    documented 3-failure retry rule.
  - Migration `0001_initial_schema` creates tables in dependency order
    (`outlets → stories → analysis_runs → articles → article_analysis →
    story_comparisons → story_overrides → ingestion_runs → eval_labels`).
  - `outlet_30d_stats.top_themes` fixed to produce `{theme: count}` via an
    inner `GROUP BY outlet_id, theme` before `jsonb_object_agg`.
