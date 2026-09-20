# NewsLens

Comparative news coverage and framing analysis across major Indian news outlets.

MCA team project. Collects articles, groups them into stories, and provides
comparative analysis of coverage, framing, sentiment, quoted sources, entities,
and themes.

The locked build contract for this project is
[`docs/architecture.md`](docs/architecture.md). Every implementation decision
must trace back to it.

## Stack

- **Backend:** FastAPI, SQLAlchemy 2.0 (asyncpg), Alembic, Groq (LLM),
  sentence-transformers (MiniLM, local).
- **Database:** PostgreSQL on Neon with pgvector + tsvector.
- **Frontend:** React + Vite + TypeScript + Recharts.
- **Ingestion:** GitHub Actions cron every 2 hours.
- **Deployment:** Vercel (frontend), Render (backend), Neon (DB).

## Repository layout

See §11 of the architecture document.

## Development setup

See §16 of the architecture document.

## Framing indicator disclaimer

NewsLens reports a **framing indicator** on a −1.0 (critical) to +1.0
(supportive) scale toward each article's primary subject, backed by observable
signals and an evidence bundle. It does **not** claim any outlet is
politically left- or right-biased. See §5 of the architecture document.
