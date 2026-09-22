"""inspect_pipeline.py — one-shot report on the current DB state.

Prints exactly the counts requested in the Week-1-Phase-1 milestone:
  - outlets count
  - articles by processing_state
  - stories with article counts and outlets
  - recent ingestion_runs
  - failed articles with error samples (first 200 chars of state_error)
  - a few sample article → story mappings

Reads DATABASE_URL from backend/.env. Never prints the URL. Read-only —
does not INSERT/UPDATE/DELETE anything.

Usage from D:\\MCA\\NewsLens\\backend on Windows:
    .\\.venv\\Scripts\\activate
    python scripts\\inspect_pipeline.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    env = BACKEND / ".env"
    if not env.exists():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        os.environ.setdefault(k, v)


_load_env()

url = os.environ.get("DATABASE_URL")
if not url:
    print("FAIL: DATABASE_URL not set (backend/.env missing).")
    sys.exit(2)

# asyncpg → psycopg for this sync-only script.
if "+asyncpg" in url:
    url = url.replace("+asyncpg", "")
if url.startswith("postgresql+psycopg://"):
    url = url.replace("postgresql+psycopg://", "postgresql://", 1)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("FAIL: psycopg not installed. pip install 'psycopg[binary]>=3.2'")
    sys.exit(2)


def hr(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("-" * 70)


def main() -> int:
    try:
        conn = psycopg.connect(url, connect_timeout=15, row_factory=dict_row)
    except psycopg.OperationalError as exc:
        print(f"FAIL: could not connect: {type(exc).__name__}: {exc}")
        return 3

    with conn.cursor() as cur:
        # -- Outlets summary
        hr("outlets")
        cur.execute("""
            SELECT o.id, o.slug, o.name, o.active,
                   (SELECT COUNT(*) FROM articles a WHERE a.outlet_id = o.id) AS article_count
              FROM outlets o
             ORDER BY o.id
        """)
        rows = cur.fetchall()
        for r in rows:
            active = "y" if r["active"] else "n"
            print(f"  id={r['id']:2}  {r['slug']:<20}  active={active}  articles={r['article_count']}")
        print(f"  total: {len(rows)} outlets")

        # -- Article counts by processing_state
        hr("articles by processing_state")
        cur.execute("""
            SELECT processing_state, COUNT(*) AS n
              FROM articles GROUP BY processing_state
             ORDER BY processing_state
        """)
        rows = cur.fetchall()
        total = 0
        for r in rows:
            print(f"  {r['processing_state']:<18}  {r['n']}")
            total += r["n"]
        print(f"  TOTAL              {total}")

        # -- Ingestion runs
        hr("recent ingestion_runs (newest first)")
        cur.execute("""
            SELECT id, status, triggered_by, articles_discovered, articles_inserted,
                   articles_failed, llm_calls,
                   EXTRACT(EPOCH FROM (completed_at - started_at))::int AS sec,
                   started_at
              FROM ingestion_runs ORDER BY id DESC LIMIT 5
        """)
        for r in cur.fetchall():
            sec = r["sec"] if r["sec"] is not None else "?"
            print(f"  id={r['id']:3}  {r['status']:8}  by={r['triggered_by']:<8}  "
                  f"disc={r['articles_discovered']:<4} ins={r['articles_inserted']:<4} "
                  f"fail={r['articles_failed']:<4} llm={r['llm_calls']:<4} "
                  f"{sec}s  {r['started_at'].strftime('%Y-%m-%d %H:%M')}")

        # -- Stories
        hr("stories (top 20 by article count)")
        cur.execute("""
            SELECT s.id, s.title, s.article_count,
                   s.first_seen_at, s.last_seen_at,
                   (SELECT string_agg(DISTINCT o.slug, ',' ORDER BY o.slug)
                    FROM articles a JOIN outlets o ON o.id = a.outlet_id
                    WHERE a.story_id = s.id) AS outlets
              FROM stories s
             ORDER BY s.article_count DESC, s.id ASC
             LIMIT 20
        """)
        for r in cur.fetchall():
            outlets = r["outlets"] or "-"
            title = (r["title"] or "")[:55]
            print(f"  id={r['id']:3}  count={r['article_count']:2}  "
                  f"outlets=[{outlets}]  {title!r}")

        # -- Story stats
        cur.execute("SELECT COUNT(*) AS n FROM stories")
        n_stories = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM stories WHERE article_count > 1")
        n_multi = cur.fetchone()["n"]
        print(f"\n  total stories: {n_stories} (of which {n_multi} span > 1 article)")

        # -- Sample article → story mappings (5 rows)
        hr("sample articles (5 most recent, showing story assignment)")
        cur.execute("""
            SELECT a.id, a.processing_state, a.attempt_count,
                   substring(a.headline, 1, 60) AS headline,
                   o.slug AS outlet,
                   a.story_id
              FROM articles a JOIN outlets o ON o.id = a.outlet_id
             ORDER BY a.id DESC LIMIT 5
        """)
        for r in cur.fetchall():
            print(f"  id={r['id']:4}  {r['outlet']:<15}  "
                  f"state={r['processing_state']:<11}  "
                  f"attempts={r['attempt_count']}  story_id={r['story_id'] or '-'}  "
                  f"{r['headline']!r}")

        # -- Failed articles with error samples
        hr("failed articles (state_error samples, up to 10)")
        cur.execute("""
            SELECT a.id, o.slug, a.processing_state, a.attempt_count,
                   substring(a.state_error, 1, 200) AS err,
                   a.url
              FROM articles a JOIN outlets o ON o.id = a.outlet_id
             WHERE a.processing_state IN
                     ('failed_extract', 'failed_embed', 'failed_analyze')
             ORDER BY a.id DESC LIMIT 10
        """)
        rows_fail = cur.fetchall()
        if not rows_fail:
            print("  (none — no articles in failed_* states)")
        else:
            for r in rows_fail:
                print(f"  id={r['id']:4}  outlet={r['slug']:<15}  state={r['processing_state']:<15}  "
                      f"attempts={r['attempt_count']}")
                print(f"      url: {r['url'][:80]}")
                print(f"      err: {(r['err'] or '')[:180]}")

        # -- fts + embedding sanity check
        hr("row-level integrity spot-check")
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE fts IS NOT NULL) AS with_fts,
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS with_embedding,
                   COUNT(*) AS total
              FROM articles
        """)
        r = cur.fetchone()
        total = r["total"] or 1
        print(f"  articles with fts populated:       {r['with_fts']}/{r['total']}  "
              f"({100*r['with_fts']//total}%)")
        print(f"  articles with embedding populated: {r['with_embedding']}/{r['total']}  "
              f"({100*r['with_embedding']//total}%)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
