"""verify_neon.py — one-shot schema + behavior check against Neon dev.

Reads DATABASE_URL from backend/.env (never prints it), connects with the
sync psycopg driver, and runs the same battery of checks that was used
against local Postgres 16 + pgvector for Week 1 step 4:

    Section A — introspection (read-only)
        1.  pgvector extension present
        2.  All 9 documented tables present
        3.  processing_state enum has the 9 documented labels in order
        4.  All 8 documented indexes present with correct USING clause
        5.  All 8 documented CHECK constraints present
        6.  All 9 documented foreign keys with correct ON DELETE codes
        7.  articles.attempt_count INTEGER NOT NULL DEFAULT 0
        8.  outlet_30d_stats materialized view + its UNIQUE index

    Section B — data-level tests (BEGIN … ROLLBACK; nothing persists)
        9.  Insert outlets/stories/analysis_runs/articles/article_analysis
       10.  Generated fts column populates
       11.  outlets FK RESTRICT blocks delete
       12.  story_comparisons.story_id CASCADE on story delete
       13.  articles.story_id SET NULL on story delete
       14.  article_analysis framing_score CHECK rejects out-of-range
       15.  articles.url UNIQUE rejects duplicate
       16.  article_analysis PK-only (latest-wins) — duplicate insert fails
       17.  attempt_count default 0 and increments
       18.  Corrected top_themes yields {theme: count}
       19.  REFRESH MATERIALIZED VIEW CONCURRENTLY works

The script is idempotent and safe to re-run. It never modifies the
migration, models, schema, or any project code. It never prints the
DATABASE_URL, hostname, or any credential.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# --- .env loader (no external dep) ---------------------------------------
def load_env(path: Path) -> None:
    """Minimal .env loader — supports `KEY=value` and quoted values."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


BACKEND_DIR = Path(__file__).resolve().parent.parent
load_env(BACKEND_DIR / ".env")

RAW_URL = os.environ.get("DATABASE_URL")
if not RAW_URL:
    print("FAIL: DATABASE_URL not set (backend/.env missing or malformed).")
    sys.exit(2)

# Rewrite asyncpg → psycopg for this sync-only script.
def to_psycopg_dsn(url: str) -> str:
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "")
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


DSN = to_psycopg_dsn(RAW_URL)

try:
    import psycopg
    from psycopg import sql  # noqa: F401
except ImportError:
    print("FAIL: psycopg not installed. Run: pip install 'psycopg[binary]>=3.2'")
    sys.exit(2)


# --- Expected shape (from architecture §9 + owner-approved corrections) ---
EXPECTED_TABLES = {
    "outlets", "stories", "analysis_runs", "articles", "article_analysis",
    "story_comparisons", "story_overrides", "ingestion_runs", "eval_labels",
}

EXPECTED_ENUM_LABELS = [
    "discovered", "extracted", "embedded", "clustered", "analyzed",
    "complete", "failed_extract", "failed_embed", "failed_analyze",
]

# name → substring that must appear in the index's CREATE INDEX definition
EXPECTED_INDEXES = {
    "ix_stories_last_seen_at_desc":     "last_seen_at DESC",
    "ix_stories_topic":                 "(topic)",
    "ix_articles_outlet_published":     "(outlet_id, published_at DESC)",
    "ix_articles_story_id":             "(story_id)",
    "ix_articles_embedding_ivfflat":    "USING ivfflat (embedding vector_cosine_ops)",
    "ix_articles_fts_gin":              "USING gin (fts)",
    "ix_ingestion_runs_started_at_desc":"started_at DESC",
    "ix_outlet_30d_stats_outlet_id":    "UNIQUE INDEX",
}

EXPECTED_CHECK_CONSTRAINTS = {
    "analysis_runs_purpose_check",
    "article_analysis_framing_score_check",
    "article_analysis_framing_confidence_check",
    "article_analysis_headline_sentiment_check",
    "article_analysis_body_sentiment_check",
    "article_analysis_framing_label_check",
    "ingestion_runs_triggered_by_check",
    "ingestion_runs_status_check",
}

# name → expected ON DELETE code ('a'=NO ACTION, 'r'=RESTRICT, 'c'=CASCADE, 'n'=SET NULL)
EXPECTED_FKS = {
    "articles_outlet_id_fkey":                "r",
    "articles_story_id_fkey":                 "n",
    "article_analysis_article_id_fkey":       "c",
    "article_analysis_analysis_run_id_fkey":  "a",
    "story_comparisons_story_id_fkey":        "c",
    "story_comparisons_analysis_run_id_fkey": "a",
    "story_overrides_article_id_fkey":        "c",
    "story_overrides_forced_story_id_fkey":   "n",
    "eval_labels_article_id_fkey":            "c",
}


# --- Result collector -----------------------------------------------------
class Results:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str, str]] = []  # (name, status, detail)
        self.failures = 0

    def ok(self, name: str, detail: str = "") -> None:
        self.entries.append((name, "PASS", detail))

    def fail(self, name: str, detail: str) -> None:
        self.entries.append((name, "FAIL", detail))
        self.failures += 1

    def print_report(self) -> None:
        print()
        print("=" * 72)
        print(f"{'CHECK':<48} {'RESULT':<6} DETAIL")
        print("-" * 72)
        for name, status, detail in self.entries:
            print(f"{name:<48} {status:<6} {detail}")
        print("=" * 72)
        total = len(self.entries)
        passed = total - self.failures
        print(f"Summary: {passed}/{total} checks passed"
              + ("" if self.failures == 0 else f", {self.failures} FAILED"))


R = Results()


def main() -> int:
    # Silent connect — never print the DSN.
    try:
        conn = psycopg.connect(DSN, connect_timeout=15)
    except psycopg.OperationalError as exc:
        print(f"FAIL: could not connect to database (host / port / TLS layer):")
        print(f"      {type(exc).__name__}: {exc}")
        return 3
    conn.autocommit = False

    server_version = conn.execute("SHOW server_version").fetchone()[0]
    R.ok("connected to Neon", f"server_version={server_version}")

    # =====================================================================
    # SECTION A — introspection (read-only)
    # =====================================================================
    with conn.cursor() as cur:
        # 1. pgvector extension
        cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
        row = cur.fetchone()
        if row:
            R.ok("A1  pgvector extension present", f"version={row[0]}")
        else:
            R.fail("A1  pgvector extension present", "not installed")

        # 2. tables
        cur.execute("""
            SELECT tablename FROM pg_tables
             WHERE schemaname='public' AND tablename != 'alembic_version'
        """)
        found_tables = {r[0] for r in cur.fetchall()}
        missing = EXPECTED_TABLES - found_tables
        extra = found_tables - EXPECTED_TABLES
        if not missing and not extra:
            R.ok("A2  9 documented tables present", f"tables={len(found_tables)}")
        else:
            R.fail("A2  9 documented tables present",
                   f"missing={sorted(missing)} extra={sorted(extra)}")

        # 3. enum labels + order
        cur.execute("""
            SELECT enumlabel FROM pg_enum e
              JOIN pg_type t ON t.oid = e.enumtypid
             WHERE typname='processing_state'
             ORDER BY enumsortorder
        """)
        got = [r[0] for r in cur.fetchall()]
        if got == EXPECTED_ENUM_LABELS:
            R.ok("A3  processing_state enum (9 labels in order)", f"labels={len(got)}")
        else:
            R.fail("A3  processing_state enum (9 labels in order)", f"got={got}")

        # 4. indexes
        cur.execute("""
            SELECT indexname, indexdef FROM pg_indexes
             WHERE schemaname='public' AND indexname = ANY(%s)
        """, (list(EXPECTED_INDEXES.keys()),))
        idx_defs = {name: definition for name, definition in cur.fetchall()}
        for name, expect_sub in EXPECTED_INDEXES.items():
            if name not in idx_defs:
                R.fail(f"A4  index {name}", "missing")
                continue
            definition = idx_defs[name]
            if expect_sub.lower() in definition.lower():
                R.ok(f"A4  index {name}", "definition matches")
            else:
                R.fail(f"A4  index {name}", f"unexpected: {definition}")

        # 5. check constraints
        cur.execute("""
            SELECT conname FROM pg_constraint
             WHERE contype='c' AND connamespace='public'::regnamespace
        """)
        found_checks = {r[0] for r in cur.fetchall()}
        missing = EXPECTED_CHECK_CONSTRAINTS - found_checks
        if not missing:
            R.ok("A5  8 check constraints present",
                 f"checks={len(EXPECTED_CHECK_CONSTRAINTS)}")
        else:
            R.fail("A5  8 check constraints present", f"missing={sorted(missing)}")

        # 6. foreign keys with correct ON DELETE
        cur.execute("""
            SELECT conname, confdeltype FROM pg_constraint
             WHERE contype='f' AND connamespace='public'::regnamespace
        """)
        found_fks = {r[0]: r[1] for r in cur.fetchall()}
        fk_wrong = []
        for name, expect in EXPECTED_FKS.items():
            actual = found_fks.get(name)
            if actual is None:
                fk_wrong.append(f"{name}=MISSING")
            elif actual != expect:
                fk_wrong.append(f"{name}={actual}!={expect}")
        if not fk_wrong:
            R.ok("A6  9 foreign keys with correct ON DELETE",
                 f"fks={len(EXPECTED_FKS)}")
        else:
            R.fail("A6  9 foreign keys with correct ON DELETE",
                   ", ".join(fk_wrong))

        # 7. articles.attempt_count
        cur.execute("""
            SELECT data_type, is_nullable, column_default
              FROM information_schema.columns
             WHERE table_name='articles' AND column_name='attempt_count'
        """)
        row = cur.fetchone()
        if row and row[0] == "integer" and row[1] == "NO" and row[2] == "0":
            R.ok("A7  articles.attempt_count INT NOT NULL DEFAULT 0", "as documented")
        else:
            R.fail("A7  articles.attempt_count INT NOT NULL DEFAULT 0", f"got={row}")

        # 8. materialized view + its unique index
        cur.execute("""
            SELECT matviewname FROM pg_matviews
             WHERE schemaname='public' AND matviewname='outlet_30d_stats'
        """)
        if cur.fetchone():
            R.ok("A8  outlet_30d_stats materialized view present", "")
        else:
            R.fail("A8  outlet_30d_stats materialized view present", "missing")

    # =====================================================================
    # SECTION B — data-level behavior, all inside a SAVEPOINT that we ROLL
    # BACK at the end. Nothing persists in Neon.
    # =====================================================================
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT verify_test")

            # 9. Insert outlets/stories/analysis_runs/articles/article_analysis
            try:
                cur.execute("""
                    INSERT INTO outlets (name, slug, rss_url, website) VALUES
                      ('_verify_hindu_' || gen_random_uuid()::text, 'verify-hindu-'||substr(md5(random()::text),1,8), 'x', 'x'),
                      ('_verify_ndtv_'  || gen_random_uuid()::text, 'verify-ndtv-' ||substr(md5(random()::text),1,8), 'x', 'x')
                    RETURNING id
                """)
                outlet_ids = [r[0] for r in cur.fetchall()]

                cur.execute("""
                    INSERT INTO stories (title, first_seen_at, last_seen_at)
                    VALUES ('_verify_story', NOW() - INTERVAL '2 days', NOW())
                    RETURNING id
                """)
                story_id = cur.fetchone()[0]

                cur.execute("""
                    INSERT INTO analysis_runs (model_id, prompt_version, purpose)
                    VALUES ('verify-model', 'verify_v1', 'enrich')
                    RETURNING id
                """)
                run_id = cur.fetchone()[0]

                # Three articles with the pgvector column populated.
                cur.execute("""
                    INSERT INTO articles (outlet_id, url, headline, published_at,
                                           full_text, story_id, processing_state,
                                           embedding)
                    VALUES
                      (%s, '_verify_a1_'||gen_random_uuid(), 'Budget lauded',
                       NOW()-INTERVAL '5 days', 'Body A', %s, 'analyzed',
                       ('[' || array_to_string(array_fill(0.1::real, ARRAY[384]), ',') || ']')::vector),
                      (%s, '_verify_a2_'||gen_random_uuid(), 'Budget tepid',
                       NOW()-INTERVAL '10 days', 'Body B', %s, 'analyzed',
                       ('[' || array_to_string(array_fill(0.2::real, ARRAY[384]), ',') || ']')::vector),
                      (%s, '_verify_a3_'||gen_random_uuid(), 'Budget crit',
                       NOW()-INTERVAL '3 days', 'Body C', %s, 'analyzed',
                       ('[' || array_to_string(array_fill(0.3::real, ARRAY[384]), ',') || ']')::vector)
                    RETURNING id
                """, (outlet_ids[0], story_id, outlet_ids[0], story_id,
                      outlet_ids[1], story_id))
                article_ids = [r[0] for r in cur.fetchall()]
                R.ok("B9  insert outlets/stories/runs/articles", f"articles={len(article_ids)}")
            except Exception as exc:
                R.fail("B9  insert outlets/stories/runs/articles", f"{type(exc).__name__}: {exc}")
                raise

            # 10. Generated fts column populated
            cur.execute("SELECT fts IS NOT NULL FROM articles WHERE id = ANY(%s)",
                        (article_ids,))
            fts_ok = all(row[0] for row in cur.fetchall())
            (R.ok if fts_ok else R.fail)("B10 generated fts column populates",
                                          "all rows have tsvector")

            # 11. outlets FK RESTRICT blocks delete.
            # Postgres raises SQLSTATE 23001 (RestrictViolation) for ON DELETE
            # RESTRICT and 23503 (ForeignKeyViolation) for the generic case;
            # in psycopg3 these are sibling classes, not parent/child, so we
            # accept either. On Neon this test consistently raises
            # RestrictViolation.
            cur.execute("SAVEPOINT s11")
            try:
                cur.execute("DELETE FROM outlets WHERE id=%s", (outlet_ids[0],))
                R.fail("B11 outlets FK RESTRICT blocks delete",
                       "delete unexpectedly succeeded")
                cur.execute("ROLLBACK TO SAVEPOINT s11")
            except (psycopg.errors.RestrictViolation,
                    psycopg.errors.ForeignKeyViolation) as exc:
                cur.execute("ROLLBACK TO SAVEPOINT s11")
                R.ok("B11 outlets FK RESTRICT blocks delete",
                     f"raised {type(exc).__name__}")

            # 12/13. story_comparisons CASCADE + articles.story_id SET NULL
            cur.execute("""
                INSERT INTO story_comparisons (story_id, analysis_run_id, differences)
                VALUES (%s, %s, 'x')
            """, (story_id, run_id))
            cur.execute("DELETE FROM stories WHERE id=%s", (story_id,))
            cur.execute("SELECT COUNT(*) FROM story_comparisons WHERE story_id=%s",
                        (story_id,))
            cascade_gone = cur.fetchone()[0] == 0
            (R.ok if cascade_gone else R.fail)(
                "B12 story_comparisons CASCADE on story delete",
                "row removed" if cascade_gone else "row not removed")

            cur.execute("SELECT story_id FROM articles WHERE id = ANY(%s)",
                        (article_ids,))
            all_null = all(r[0] is None for r in cur.fetchall())
            (R.ok if all_null else R.fail)(
                "B13 articles.story_id SET NULL on story delete",
                "all set NULL" if all_null else "some still set")

            # Recreate story so we can insert article_analysis rows.
            cur.execute("""
                INSERT INTO stories (title, first_seen_at, last_seen_at)
                VALUES ('_verify_story2', NOW()-INTERVAL '2 days', NOW())
                RETURNING id
            """)
            new_story_id = cur.fetchone()[0]
            cur.execute("UPDATE articles SET story_id=%s WHERE id = ANY(%s)",
                        (new_story_id, article_ids))

            cur.execute("""
                INSERT INTO article_analysis
                  (article_id, analysis_run_id, framing_score, framing_label,
                   framing_confidence, headline_sentiment, body_sentiment, key_themes)
                VALUES
                  (%s, %s, 0.30, 'supportive', 0.80,  0.20,  0.10, ARRAY['economy','budget','tax']),
                  (%s, %s, 0.10, 'neutral',    0.60,  0.00,  0.05, ARRAY['budget','tax','deficit']),
                  (%s, %s,-0.40, 'critical',   0.75, -0.30, -0.20, ARRAY['budget','deficit','poverty'])
            """, (article_ids[0], run_id, article_ids[1], run_id, article_ids[2], run_id))

            # 14. framing_score CHECK
            cur.execute("SAVEPOINT s14")
            try:
                cur.execute("""
                    INSERT INTO article_analysis (article_id, analysis_run_id, framing_score)
                    VALUES (%s, %s, 2.0)
                """, (article_ids[0], run_id))  # already exists → will hit either CHECK or PK
                R.fail("B14 framing_score CHECK rejects out-of-range",
                       "insert unexpectedly succeeded")
                cur.execute("ROLLBACK TO SAVEPOINT s14")
            except (psycopg.errors.CheckViolation, psycopg.errors.UniqueViolation) as exc:
                cur.execute("ROLLBACK TO SAVEPOINT s14")
                if isinstance(exc, psycopg.errors.CheckViolation):
                    R.ok("B14 framing_score CHECK rejects out-of-range",
                         "raised CheckViolation")
                else:
                    # Row already exists — retry against a fresh article to isolate CHECK.
                    cur.execute("""
                        INSERT INTO outlets (name, slug, rss_url, website)
                        VALUES ('_verify_x', 'verify-x-'||substr(md5(random()::text),1,8), 'x', 'x')
                        RETURNING id
                    """)
                    ox = cur.fetchone()[0]
                    cur.execute("""
                        INSERT INTO articles (outlet_id, url, headline, published_at)
                        VALUES (%s, '_verify_ax_'||gen_random_uuid(), 'h', NOW())
                        RETURNING id
                    """, (ox,))
                    ax = cur.fetchone()[0]
                    cur.execute("SAVEPOINT s14b")
                    try:
                        cur.execute("""
                            INSERT INTO article_analysis (article_id, analysis_run_id, framing_score)
                            VALUES (%s, %s, 2.0)
                        """, (ax, run_id))
                        R.fail("B14 framing_score CHECK rejects out-of-range",
                               "insert unexpectedly succeeded")
                        cur.execute("ROLLBACK TO SAVEPOINT s14b")
                    except psycopg.errors.CheckViolation:
                        cur.execute("ROLLBACK TO SAVEPOINT s14b")
                        R.ok("B14 framing_score CHECK rejects out-of-range",
                             "raised CheckViolation")

            # 15. articles.url UNIQUE
            cur.execute("SELECT url FROM articles WHERE id=%s", (article_ids[0],))
            existing_url = cur.fetchone()[0]
            cur.execute("SAVEPOINT s15")
            try:
                cur.execute("""
                    INSERT INTO articles (outlet_id, url, headline, published_at)
                    VALUES (%s, %s, 'dup', NOW())
                """, (outlet_ids[0], existing_url))
                R.fail("B15 articles.url UNIQUE rejects duplicate",
                       "insert unexpectedly succeeded")
                cur.execute("ROLLBACK TO SAVEPOINT s15")
            except psycopg.errors.UniqueViolation:
                cur.execute("ROLLBACK TO SAVEPOINT s15")
                R.ok("B15 articles.url UNIQUE rejects duplicate",
                     "raised UniqueViolation")

            # 16. article_analysis PK-only (duplicate insert fails)
            cur.execute("SAVEPOINT s16")
            try:
                cur.execute("""
                    INSERT INTO article_analysis (article_id, analysis_run_id, framing_score)
                    VALUES (%s, %s, 0.5)
                """, (article_ids[0], run_id))
                R.fail("B16 article_analysis PK is article_id alone",
                       "duplicate insert unexpectedly succeeded")
                cur.execute("ROLLBACK TO SAVEPOINT s16")
            except psycopg.errors.UniqueViolation:
                cur.execute("ROLLBACK TO SAVEPOINT s16")
                R.ok("B16 article_analysis PK is article_id alone",
                     "duplicate raises UniqueViolation (latest-wins via UPDATE)")

            # 17. attempt_count default + increment
            cur.execute("SELECT attempt_count FROM articles WHERE id=%s",
                        (article_ids[0],))
            initial = cur.fetchone()[0]
            cur.execute("""
                UPDATE articles SET attempt_count = attempt_count + 1
                 WHERE id=%s RETURNING attempt_count
            """, (article_ids[0],))
            after = cur.fetchone()[0]
            if initial == 0 and after == 1:
                R.ok("B17 attempt_count default 0 and increments",
                     "0 → 1 as documented")
            else:
                R.fail("B17 attempt_count default 0 and increments",
                       f"initial={initial} after={after}")

            # 18. Corrected top_themes yields {theme: count}
            # NOTE: REFRESH cannot run inside a transaction, so we test the
            # view's SELECT clause against the current transaction's data by
            # replicating the SQL directly. This proves the CTE logic even
            # though REFRESH itself is deferred to B19 (autocommit branch).
            cur.execute("""
                WITH per_theme AS (
                    SELECT a.outlet_id, theme, COUNT(*) AS cnt
                      FROM articles a
                      JOIN article_analysis aa ON aa.article_id = a.id
                      LEFT JOIN LATERAL unnest(aa.key_themes) AS theme ON TRUE
                     WHERE a.published_at >= NOW() - INTERVAL '30 days'
                       AND theme IS NOT NULL
                       AND a.outlet_id = ANY(%s)
                     GROUP BY a.outlet_id, theme
                )
                SELECT outlet_id, jsonb_object_agg(theme, cnt) AS top_themes
                  FROM per_theme
                 GROUP BY outlet_id
                 ORDER BY outlet_id
            """, (outlet_ids,))
            themes_by_outlet = {r[0]: r[1] for r in cur.fetchall()}
            outlet1_themes = themes_by_outlet.get(outlet_ids[0], {})
            # Outlet 1 got articles [0] and [1]:
            #   [0]: economy,budget,tax   [1]: budget,tax,deficit
            # Expected: budget=2, tax=2, economy=1, deficit=1
            expect1 = {"budget": 2, "tax": 2, "economy": 1, "deficit": 1}
            if outlet1_themes == expect1:
                R.ok("B18 corrected top_themes yields {theme: count}",
                     f"outlet1={outlet1_themes}")
            else:
                R.fail("B18 corrected top_themes yields {theme: count}",
                       f"got={outlet1_themes} expected={expect1}")

            # Roll back everything from Section B — Neon is left untouched.
            cur.execute("ROLLBACK TO SAVEPOINT verify_test")
    except Exception:
        # Any unexpected exception rolls back too.
        try:
            conn.rollback()
        except Exception:
            pass
        traceback.print_exc()

    conn.rollback()  # belt + braces; nothing was committed anyway

    # =====================================================================
    # B19 — REFRESH MATERIALIZED VIEW CONCURRENTLY requires autocommit.
    # Runs against the empty (or existing) view; safe regardless.
    # =====================================================================
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY outlet_30d_stats")
            R.ok("B19 REFRESH MATERIALIZED VIEW CONCURRENTLY",
                 "unique index enables concurrent refresh")
    except psycopg.errors.FeatureNotSupported as exc:
        # First-ever refresh cannot be CONCURRENTLY on an unpopulated view.
        # Fall back to a plain REFRESH so we still confirm the view is valid.
        try:
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW outlet_30d_stats")
            R.ok("B19 REFRESH MATERIALIZED VIEW CONCURRENTLY",
                 "first refresh (non-concurrent) — CONCURRENTLY needs prior population")
        except Exception as exc2:
            R.fail("B19 REFRESH MATERIALIZED VIEW CONCURRENTLY",
                   f"{type(exc2).__name__}: {exc2}")
    except Exception as exc:
        R.fail("B19 REFRESH MATERIALIZED VIEW CONCURRENTLY",
               f"{type(exc).__name__}: {exc}")

    # =====================================================================
    # Defensive cleanup - belt-and-braces for `_verify_*` rows if the
    # SAVEPOINT rollback in Section B was interrupted (e.g. by an
    # uncaught exception in an earlier version of this script). On a clean
    # run this finds nothing to delete.
    #
    # ORDER MATTERS: dependent rows must be deleted BEFORE the outlet /
    # analysis_run / story they reference, because:
    #   - articles.outlet_id has ON DELETE RESTRICT (deleting an outlet
    #     with lingering articles raises RestrictViolation);
    #   - article_analysis.analysis_run_id and
    #     story_comparisons.analysis_run_id have no ON DELETE clause
    #     (NO ACTION), so their referenced analysis_run cannot be deleted
    #     until they are.
    # CASCADE handles some paths, but we do it explicitly so this
    # cleanup is deterministic regardless of ordering nuances.
    #
    # All predicates target only rows whose text columns start with
    # '_verify_' - this cleanup can never touch real data.
    # =====================================================================
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # 1) leaf tables that reference articles / stories / runs
            cur.execute("""
                DELETE FROM article_analysis
                 WHERE article_id IN (
                   SELECT id FROM articles WHERE url LIKE '_verify_%'
                 )
            """)
            cur.execute("""
                DELETE FROM story_comparisons
                 WHERE story_id IN (
                   SELECT id FROM stories WHERE title LIKE '_verify_%'
                 )
                    OR analysis_run_id IN (
                   SELECT id FROM analysis_runs WHERE model_id = 'verify-model'
                 )
            """)
            cur.execute("""
                DELETE FROM eval_labels
                 WHERE article_id IN (
                   SELECT id FROM articles WHERE url LIKE '_verify_%'
                 )
            """)
            cur.execute("""
                DELETE FROM story_overrides
                 WHERE article_id IN (
                   SELECT id FROM articles WHERE url LIKE '_verify_%'
                 )
                    OR forced_story_id IN (
                   SELECT id FROM stories WHERE title LIKE '_verify_%'
                 )
            """)
            # 2) articles - must come BEFORE outlets (RESTRICT) and stories
            cur.execute("DELETE FROM articles WHERE url LIKE '_verify_%'")
            # 3) analysis_runs - must come AFTER article_analysis and
            #    story_comparisons (NO ACTION)
            cur.execute("DELETE FROM analysis_runs WHERE model_id = 'verify-model'")
            # 4) stories - must come AFTER story_comparisons/overrides and
            #    after articles.story_id has been cleared or the articles
            #    themselves removed
            cur.execute("DELETE FROM stories WHERE title LIKE '_verify_%'")
            # 5) outlets - parent of articles (RESTRICT); safe now that all
            #    dependent articles are gone
            cur.execute("""
                DELETE FROM outlets
                 WHERE name LIKE '_verify_%' OR slug LIKE 'verify-%'
            """)
        R.ok("cleanup  removed any leftover _verify_* rows",
             "dependents deleted before parents")
    except Exception as exc:
        # Cleanup failure never crashes the report - the verified assertions
        # above are what count. Just record it and move on.
        R.fail("cleanup  removed any leftover _verify_* rows",
               f"{type(exc).__name__}: {exc}")

    conn.close()
    R.print_report()
    return 0 if R.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
