# Running the ingestion pipeline against Neon

Claude built and validated the full Phase-1 ingestion pipeline against a
local Postgres 16 + pgvector clone of the Neon schema. The pipeline is
ready to run against real Neon + real Indian news feeds from your Windows
machine. This document is what you do.

## Prerequisites (one-time)

From `D:\MCA\NewsLens\backend` in PowerShell:

```powershell
# You already have .venv from the earlier verify_neon step. If not:
py -3.11 -m venv .venv
.\.venv\Scripts\activate

# Full set of production deps for the ingestion pipeline
pip install "sqlalchemy>=2.0" "alembic>=1.13" "psycopg[binary]>=3.2" ^
            "asyncpg>=0.29" "pgvector>=0.3" ^
            "pydantic>=2.7" "pydantic-settings>=2.4" ^
            "feedparser>=6.0" "httpx>=0.27" "trafilatura>=1.12" ^
            "python-dateutil>=2.9" "pyyaml>=6.0" "tenacity>=9.0" ^
            "numpy>=1.26" "sentence-transformers>=3.0"
```

`sentence-transformers` pulls in torch and downloads the ~90MB MiniLM
model on first use, cached under `~/.cache/huggingface`. Give it 5
minutes on a slow network the first time.

## Step 1 — Verify the 5 RSS feeds are live

Claude used the canonical URLs the outlets have published for years, but
websites move things. Confirm all 5 are still parseable:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python scripts\verify_feeds.py
```

Expected: last line reads `PASS: all 5 feeds live and parseable`. If any
line is marked `!`, edit `src\ingestion\outlets.yaml` with the correct
URL and re-run.

## Step 2 — Seed outlets (idempotent)

```powershell
python -m src.ingestion.seed
```

First run inserts 5 rows into `outlets`. Subsequent runs report
`inserted=0 updated=0 unchanged=5`.

## Step 3 — Run one full ingestion cycle

```powershell
python -m src.ingestion.run --once
```

What this does (per architecture §10):
1. Opens an `ingestion_runs` row with status='running'.
2. For each active Phase-1 outlet, fetches the RSS feed and inserts new
   URLs into `articles` (state=`discovered`; existing URLs skipped).
3. Downloads each `discovered` article and extracts main body text via
   trafilatura → state=`extracted`. On failure, `attempt_count`
   increments; on the 3rd failure the row moves to `failed_extract`.
4. Embeds `extracted` articles with MiniLM → state=`embedded`.
5. Clusters `embedded` articles into stories via pgvector cosine
   similarity (threshold 0.75, 3-day window) → state=`clustered`.
6. Closes the ingestion_runs row with status='success'.

Run it a second time — you should see near-zero new discoveries and no
duplicate articles, proving URL dedup works.

### Useful flags

| flag | when to use |
|---|---|
| `--phase phase_1 --phase phase_2` | broader set once Phase-2 is added |
| `--skip-embed` | discover+extract only (no MiniLM download needed) |
| `--skip-cluster` | embed but don't cluster |
| `--hash-embedder` | deterministic fake embedder for smoke tests |
| `--triggered-by cron` | mark the run as cron-triggered |

## Step 4 — Inspect what happened

```powershell
python -c "
import os
from sqlalchemy import create_engine, text
url = open('.env').read().split('DATABASE_URL=',1)[1].split('\n',1)[0].replace('+asyncpg','')
if url.startswith('postgresql://'): url = url.replace('postgresql://','postgresql+psycopg://',1)
e = create_engine(url)
with e.connect() as c:
    for q in [
        'SELECT COUNT(*) FROM outlets',
        'SELECT COUNT(*) FROM articles',
        'SELECT COUNT(*) FROM stories',
        'SELECT processing_state, COUNT(*) FROM articles GROUP BY processing_state ORDER BY 1',
        'SELECT id, status, articles_discovered, articles_inserted, articles_failed FROM ingestion_runs ORDER BY id DESC LIMIT 3',
    ]:
        print('---', q, '---')
        for r in c.execute(text(q)).all():
            print(r)
"
```

## Step 5 — Run the tests

```powershell
$env:DATABASE_URL_TEST = $env:DATABASE_URL   # if not already set
pytest tests\test_ingestion.py -v
```

Expected: `16 passed`.

## GitHub Actions

The existing `.github/workflows/ingest.yml` triggers `python -m
src.ingestion.run` on a 2-hour cron, but the schedule is commented out
until Phase-1 is confirmed clean on Neon. When you're happy with a few
manual runs, uncomment the `schedule:` block.

## Troubleshooting

- `MiniLM unavailable` on first call → the model download failed (no
  internet or hf.co blocked). Retry, or use `--hash-embedder` for a
  smoke run.
- `failed_extract` articles → check `state_error` on those rows; usually
  a paywall or a JS-rendered page. Trafilatura can't fix those; the
  articles stay quarantined and the next runs skip them.
- Ingestion crashed mid-run → the `ingestion_runs` row's status is
  `failed` with a truncated traceback in `error`. Article rows keep
  their state and attempt_count, so the next run picks up where this
  one left off. That is by design (§10 "no article silently
  disappears").
