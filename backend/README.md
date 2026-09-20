# newslens-backend

The FastAPI + ingestion + analysis backend for **NewsLens**, an MCA team
project on comparative news coverage and framing indicators across major
Indian news outlets.

Project-wide documentation lives in the repository root:

- [Repository README](../README.md) — high-level project overview
- [`docs/architecture.md`](../docs/architecture.md) — locked build contract
  (source of truth; see the linked `NewsLens_Architecture_v2.md` for the
  full spec)
- [`docs/RUN_INGESTION.md`](../docs/RUN_INGESTION.md) — how to run the
  ingestion pipeline against Neon from a Windows PowerShell

## Backend layout

- `src/` — Python package (`main.py`, `config.py`, `db/`, `api/`,
  `ingestion/`, `prompts/`, `experimental/`, `export/`, `eval/`)
- `alembic/` — database migrations (single source of truth for the schema)
- `scripts/` — one-off operational scripts (`verify_neon.py`,
  `verify_feeds.py`)
- `tests/` — pytest suite

## Development

```bash
python -m venv .venv
. .venv/bin/activate       # Windows: .\.venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env       # then fill in DATABASE_URL, GROQ_API_KEY, LLM_MODEL
export PYTHONPATH="$PWD"   # Windows: $env:PYTHONPATH = (Get-Location).Path
alembic upgrade head
python -m src.ingestion.seed
python -m src.ingestion.run --once
```

See `docs/RUN_INGESTION.md` for the full end-to-end walkthrough.
