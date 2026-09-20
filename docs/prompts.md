# Prompts

Every LLM call in NewsLens uses a **versioned prompt file** committed under
`backend/src/prompts/`. This document indexes prompt files, their inputs and
outputs, and the reasoning behind each revision.

## Conventions

- Filename: `<step>_v<N>.txt` (e.g. `enrich_v1.txt`, `compare_v2.txt`).
- Each version is a new file — old versions are **never overwritten** so
  every `analysis_runs` row can be reproduced against the prompt it used.
- The current version in use for each step is recorded in
  `analysis_runs.prompt_version`.

## Registry

| Step | Current version | File | Notes |
|---|---|---|---|
| enrich | (Week 2) | `enrich_v1.txt` | Placeholder scaffolded; content lands in Week 2. |
| compare | (Week 2) | `compare_v1.txt` | Placeholder scaffolded; content lands in Week 2. |

## Change log

- `2026-09-20` — Files created as empty placeholders during Week 1 scaffold.
