"""enrich_sample.py — Part 2 controlled Groq-enrichment harness.

Runs the EXISTING production enrichment pipeline against a bounded,
diverse sample of ~20 clustered articles selected from the live Neon
dev database. Uses:

  - ``src.ingestion.enrich.GroqClient``   (real Groq SDK client)
  - ``src.ingestion.enrich.enrich_articles``   (production dispatch fn)
  - ``src.prompts.enrich_v1.txt``   (versioned prompt)
  - ``src.ingestion.enrich_schema.EnrichmentResponse``   (validator)

There is NO fake or mock LLM path anywhere in this script. If
``GROQ_API_KEY`` is missing, the script refuses to run.

Never prints DATABASE_URL, GROQ_API_KEY, or any secret. Prints the
selected article IDs, outlet, story_id, headline (no article bodies)
and a compact post-run report from the DB.

Usage (from D:\\MCA\\NewsLens\\backend, .venv active, $env:PYTHONPATH set):

    python scripts\\enrich_sample.py --env-check       # verify env vars only
    python scripts\\enrich_sample.py --dry-run         # select + print, no LLM
    python scripts\\enrich_sample.py --run             # select + enrich + verify
    python scripts\\enrich_sample.py --verify          # inspect the last enrich run only

The ``--run`` mode writes a JSON snapshot to
scripts/logs/part2_enrich_<UTC>.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make src.* importable when running from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select, text        # noqa: E402
from sqlalchemy.orm import Session, sessionmaker          # noqa: E402

from src.config import get_settings                        # noqa: E402
from src.db.models import AnalysisRun                     # noqa: E402
from src.ingestion.enrich import (                         # noqa: E402
    DEFAULT_PROMPT_VERSION,
    GroqClient,
    enrich_articles,
)

log = logging.getLogger("enrich_sample")

SAMPLE_TARGET = 20


# ---------------------------------------------------------------------------
# Grounding-check normalization
#
# The byte-exact substring test that the previous version of this script
# used flagged a large number of "misses" that were really just harmless
# Unicode-punctuation differences (curly quotes, non-breaking spaces,
# non-breaking hyphens, en/em dashes, HTML entities). Those are stylistic
# character-encoding differences between the model output and the
# extracted article body — the underlying words are identical.
#
# THIS IS A VERIFICATION NORMALIZATION ONLY. It does NOT alter the
# stored model output or the article body — it is only used inside this
# script's grounding check to decide whether the model's excerpt exists
# in the article body under a reasonable equivalence relation. Nothing
# here writes to the database.
# ---------------------------------------------------------------------------
import re as _re  # local alias so `re` at module scope stays available

_GROUNDING_TRANSLATIONS: dict[int, str] = {
    0x2018: "'",   # left single quotation mark
    0x2019: "'",   # right single quotation mark
    0x201C: '"',   # left double quotation mark
    0x201D: '"',   # right double quotation mark
    0x2013: "-",   # en dash
    0x2014: "-",   # em dash
    0x2011: "-",   # non-breaking hyphen
    0x2010: "-",   # hyphen
    0x00A0: " ",   # no-break space
    0x2009: " ",   # thin space
    0x202F: " ",   # narrow no-break space
    0x200B: "",    # zero-width space
    0x2026: "...", # horizontal ellipsis (kept as three dots; not a bridge)
}


def _grounding_normalize(s: str) -> str:
    """Case- and Unicode-fold the string for the grounding check only.

    Applies the punctuation/space translations above, collapses runs of
    whitespace, and lowercases. Idempotent. Never mutates any stored
    field — only used inside this script's grounding math.
    """
    if not s:
        return ""
    s = s.translate(_GROUNDING_TRANSLATIONS)
    s = _re.sub(r"\s+", " ", s).strip().lower()
    return s


# ---------------------------------------------------------------------------
# Env check
# ---------------------------------------------------------------------------
def env_check() -> int:
    """Verify DATABASE_URL, GROQ_API_KEY, LLM_MODEL are set. Never print values."""
    try:
        settings = get_settings()
    except Exception as exc:
        print(f"env: FAILED to load settings ({type(exc).__name__}): "
              f"{str(exc)[:200]}")
        return 1

    db_ok = bool(settings.database_url)
    groq_ok = bool(settings.groq_api_key)
    model_ok = bool(settings.llm_model)

    # LLM_MODEL is a model NAME (e.g. 'llama-3.1-70b-versatile'), not a
    # secret — printing it is safe and useful.
    print(f"env: DATABASE_URL      set={db_ok}")
    print(f"env: GROQ_API_KEY      set={groq_ok}  "
          f"length={len(settings.groq_api_key) if groq_ok else 0}")
    print(f"env: LLM_MODEL         set={model_ok}  value={settings.llm_model!r}")

    ok = db_ok and groq_ok and model_ok
    print(f"env: overall           {'OK' if ok else 'MISSING'}")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Sample selection
# ---------------------------------------------------------------------------
def select_sample(session: Session, target: int = SAMPLE_TARGET) -> list[dict]:
    """Select ~target diverse clustered articles.

    Priority order:
      1. Multi-outlet stories (>=2 distinct outlets in the same story) —
         take up to 3 articles per story, up to 4 stories.
      2. Fill remainder with recent singletons, preferring outlets
         underrepresented so far.
      3. Every article must have non-empty ``full_text`` and be in
         ``clustered`` state.
    """
    # Step 1: find multi-outlet stories among clustered articles, largest first.
    multi_stories = session.execute(text("""
        SELECT s.id,
               COUNT(a.id)                          AS article_count,
               COUNT(DISTINCT a.outlet_id)          AS outlet_count
          FROM stories s
          JOIN articles a ON a.story_id = s.id
         WHERE a.processing_state = 'clustered'
           AND LENGTH(COALESCE(a.full_text, '')) > 0
         GROUP BY s.id
        HAVING COUNT(DISTINCT a.outlet_id) >= 2
         ORDER BY outlet_count DESC, article_count DESC, s.id DESC
         LIMIT 4
    """)).mappings().all()

    picked: dict[int, dict] = {}  # article_id -> row dict
    per_outlet: dict[str, int] = {}

    def _add(rows):
        for row in rows:
            if row["id"] in picked:
                continue
            if len(picked) >= target:
                return
            picked[row["id"]] = dict(row)
            per_outlet[row["outlet_slug"]] = per_outlet.get(row["outlet_slug"], 0) + 1

    # From each multi-outlet story, pick up to 3 articles, one per outlet where possible.
    for s in multi_stories:
        rows = session.execute(text("""
            SELECT DISTINCT ON (a.outlet_id)
                   a.id, a.headline, a.published_at, a.story_id,
                   o.slug AS outlet_slug, o.name AS outlet_name
              FROM articles a
              JOIN outlets o ON o.id = a.outlet_id
             WHERE a.story_id = :sid
               AND a.processing_state = 'clustered'
               AND LENGTH(COALESCE(a.full_text, '')) > 0
             ORDER BY a.outlet_id, a.published_at DESC
             LIMIT 3
        """), {"sid": s["id"]}).mappings().all()
        _add(rows)
        if len(picked) >= target:
            break

    # Step 2: fill remainder with recent singletons, biasing toward outlets
    # underrepresented so far. Ints are inlined (validated as int() first) so
    # no user input reaches SQL text — safe against injection.
    remaining = target - len(picked)
    if remaining > 0:
        excluded_ids = [int(i) for i in picked.keys()] or [0]
        ex_sql = ",".join(str(i) for i in excluded_ids)
        rows = session.execute(text(f"""
            SELECT a.id, a.headline, a.published_at, a.story_id,
                   o.slug AS outlet_slug, o.name AS outlet_name
              FROM articles a
              JOIN outlets o ON o.id = a.outlet_id
             WHERE a.processing_state = 'clustered'
               AND LENGTH(COALESCE(a.full_text, '')) > 0
               AND a.id NOT IN ({ex_sql})
             ORDER BY a.published_at DESC, a.id DESC
             LIMIT 200
        """)).mappings().all()

        # Prefer least-represented outlet first for diversity.
        while remaining > 0 and rows:
            rows_sorted = sorted(
                rows,
                key=lambda r: (per_outlet.get(r["outlet_slug"], 0), -r["id"]),
            )
            next_row = rows_sorted[0]
            picked[next_row["id"]] = dict(next_row)
            per_outlet[next_row["outlet_slug"]] = per_outlet.get(next_row["outlet_slug"], 0) + 1
            remaining -= 1
            rows = [r for r in rows if r["id"] != next_row["id"]]

    return list(picked.values())


def print_sample_table(sample: list[dict]) -> None:
    print()
    print(f"Selected {len(sample)} clustered articles:")
    print(f"{'id':>5}  {'outlet':<18}  {'story':>5}  headline")
    print("-" * 100)
    for r in sample:
        head = (r["headline"] or "")[:70]
        print(f"{r['id']:>5}  {r['outlet_slug']:<18}  {r['story_id']:>5}  {head}")
    print()
    per_outlet: dict[str, int] = {}
    per_story: dict[int, int] = {}
    for r in sample:
        per_outlet[r["outlet_slug"]] = per_outlet.get(r["outlet_slug"], 0) + 1
        per_story[r["story_id"]] = per_story.get(r["story_id"], 0) + 1
    print("Outlet mix:", ", ".join(f"{k}={v}" for k, v in sorted(per_outlet.items())))
    multi = sum(1 for c in per_story.values() if c > 1)
    print(f"Stories represented: {len(per_story)}  (of which {multi} carry >1 sampled article)")
    print()


# ---------------------------------------------------------------------------
# Post-run inspection
# ---------------------------------------------------------------------------
def inspect_run(session: Session, run_id: int, sample_ids: list[int]) -> dict:
    """Read back the analysis_runs row + article_analysis rows created."""
    run = session.execute(
        select(AnalysisRun).where(AnalysisRun.id == run_id)
    ).scalar_one()

    # Column-type reminder (from src/db/models.py::ArticleAnalysis):
    #   key_themes           text[]     -> array_length + COALESCE (text[])
    #   entities             jsonb
    #   quoted_sources       jsonb      -> jsonb_array_length (via typeof guard)
    #   source_distribution  jsonb
    #   evidence_snippets    jsonb      -> jsonb_array_length (via typeof guard)
    #
    # Previous version mistakenly treated evidence_snippets as text[] and
    # tried to COALESCE it with ARRAY[]::text[], which PG rejects with
    # "COALESCE types jsonb and text[] cannot be matched".
    analyses = session.execute(text("""
        SELECT aa.article_id,
               a.story_id,
               o.slug              AS outlet,
               a.headline,
               a.processing_state::text AS state,
               a.attempt_count,
               aa.framing_score,
               aa.framing_label,
               aa.framing_confidence,
               aa.headline_sentiment,
               aa.body_sentiment,
               array_length(COALESCE(aa.key_themes, ARRAY[]::text[]), 1) AS themes_n,
               jsonb_array_length(
                    CASE jsonb_typeof(aa.quoted_sources)
                         WHEN 'array' THEN aa.quoted_sources
                         ELSE '[]'::jsonb END
               ) AS quoted_n,
               jsonb_array_length(
                    CASE jsonb_typeof(aa.evidence_snippets)
                         WHEN 'array' THEN aa.evidence_snippets
                         ELSE '[]'::jsonb END
               ) AS evidence_n,
               aa.analyzed_at,
               aa.key_themes,
               aa.quoted_sources,
               aa.evidence_snippets,
               aa.entities
          FROM article_analysis aa
          JOIN articles a ON a.id = aa.article_id
          JOIN outlets o  ON o.id = a.outlet_id
         WHERE aa.analysis_run_id = :rid
         ORDER BY aa.article_id
    """), {"rid": run_id}).mappings().all()

    # Also inspect the sampled articles that did NOT produce an analysis
    # row (i.e. those still in 'clustered' with attempts>0, or promoted
    # to 'failed_analyze').
    unanalyzed_ids = [i for i in sample_ids if i not in {r["article_id"] for r in analyses}]
    unanalyzed = []
    if unanalyzed_ids:
        rows = session.execute(text(f"""
            SELECT a.id, a.processing_state::text AS state, a.attempt_count,
                   a.state_error, o.slug AS outlet
              FROM articles a
              JOIN outlets o ON o.id = a.outlet_id
             WHERE a.id IN ({','.join(str(int(i)) for i in unanalyzed_ids)})
             ORDER BY a.id
        """)).mappings().all()
        unanalyzed = [dict(r) for r in rows]

    # Sanity: cross-check no article_analysis row was written for
    # articles OUTSIDE the sample.
    other_analyses = session.execute(text(f"""
        SELECT COUNT(*) FROM article_analysis
         WHERE analysis_run_id = :rid
           AND article_id NOT IN ({','.join(str(int(i)) for i in sample_ids) or '0'})
    """), {"rid": run_id}).scalar_one()

    return {
        "run": {
            "id": run.id,
            "ran_at": run.ran_at.isoformat(),
            "model_id": run.model_id,
            "prompt_version": run.prompt_version,
            "purpose": run.purpose,
        },
        "analyses": [_analysis_row_to_report(dict(r)) for r in analyses],
        "unanalyzed": unanalyzed,
        "other_analyses_for_this_run": int(other_analyses or 0),
    }


def _analysis_row_to_report(r: dict) -> dict:
    """Trim + summarise one article_analysis row for the JSON snapshot."""
    qs = r["quoted_sources"] or []
    entities = r["entities"] or {}
    themes = r["key_themes"] or []
    evidence = r["evidence_snippets"] or []
    return {
        "article_id":         r["article_id"],
        "story_id":           r["story_id"],
        "outlet":             r["outlet"],
        "headline":           r["headline"],
        "state_after":        r["state"],
        "attempt_count":      int(r["attempt_count"] or 0),
        "framing_score":      float(r["framing_score"]) if r["framing_score"] is not None else None,
        "framing_label":      r["framing_label"],
        "framing_confidence": float(r["framing_confidence"]) if r["framing_confidence"] is not None else None,
        "headline_sentiment": float(r["headline_sentiment"]) if r["headline_sentiment"] is not None else None,
        "body_sentiment":     float(r["body_sentiment"]) if r["body_sentiment"] is not None else None,
        "themes_count":       int(r["themes_n"] or 0),
        "entities_totals": {
            "people":        len(entities.get("people", []) or []),
            "organizations": len(entities.get("organizations", []) or []),
            "locations":     len(entities.get("locations", []) or []),
            "other":         len(entities.get("other", []) or []),
        },
        "quoted_sources_count":  int(r["quoted_n"] or 0),
        "evidence_snippet_count": int(r["evidence_n"] or 0),
        "themes_sample":         list(themes)[:6],
        "first_evidence_snippet": (evidence[0][:200] if evidence else None),
        "first_quoted_source": (
            {
                "speaker":  qs[0].get("speaker", "")[:80],
                "stance":   qs[0].get("stance", ""),
                "affiliation_present": bool(qs[0].get("affiliation")),
                "quote_head": (qs[0].get("quote", "") or "")[:120],
            } if qs else None
        ),
        "analyzed_at":  r["analyzed_at"].isoformat() if r["analyzed_at"] else None,
    }


def print_inspection(report: dict) -> None:
    r = report["run"]
    print()
    print("=" * 78)
    print(f"analysis_runs row #{r['id']}")
    print("=" * 78)
    print(f"  purpose:        {r['purpose']}")
    print(f"  model_id:       {r['model_id']}")
    print(f"  prompt_version: {r['prompt_version']}")
    print(f"  ran_at:         {r['ran_at']}")
    print()
    print(f"article_analysis rows produced by this run: {len(report['analyses'])}")
    print(f"other_analyses_for_this_run (should be 0):  "
          f"{report['other_analyses_for_this_run']}")
    print()
    for a in report["analyses"]:
        print(f"  aid={a['article_id']:<5} story={a['story_id']:<5} "
              f"outlet={a['outlet']:<18} state={a['state_after']}")
        print(f"      framing_score={a['framing_score']} "
              f"label={a['framing_label']} conf={a['framing_confidence']}")
        print(f"      sentiments hd={a['headline_sentiment']} "
              f"body={a['body_sentiment']}")
        print(f"      themes={a['themes_count']} entities="
              f"P{a['entities_totals']['people']}/"
              f"O{a['entities_totals']['organizations']}/"
              f"L{a['entities_totals']['locations']}  "
              f"quoted={a['quoted_sources_count']} "
              f"evidence={a['evidence_snippet_count']}")
        print(f"      themes: {a['themes_sample']}")
        if a["first_evidence_snippet"]:
            print(f"      evidence[0]: {a['first_evidence_snippet']!r}")
        if a["first_quoted_source"]:
            fs = a["first_quoted_source"]
            print(f"      quoted[0]: {fs['speaker']!r} ({fs['stance']}) — "
                  f"{fs['quote_head']!r}")
        print(f"      headline: {a['headline'][:74]!r}")
        print()

    if report["unanalyzed"]:
        print("Sampled articles that did NOT produce an analysis row:")
        for u in report["unanalyzed"]:
            print(f"  aid={u['id']:<5} outlet={u['outlet']:<18} "
                  f"state={u['state']:<16} attempts={u['attempt_count']} "
                  f"err={(u['state_error'] or '')[:120]!r}")
        print()


# ---------------------------------------------------------------------------
# Data-quality checks
# ---------------------------------------------------------------------------
def data_quality_checks(session: Session, run_id: int) -> dict:
    """Cross-cutting sanity checks per user's Step 5D."""
    out: dict = {}

    # Range checks (defence in depth — Pydantic already validated, but
    # this proves the DB stored what we sent).
    out["out_of_range_framing_score"] = int(session.execute(text("""
        SELECT COUNT(*) FROM article_analysis
         WHERE analysis_run_id = :rid
           AND (framing_score < -1.0 OR framing_score > 1.0)
    """), {"rid": run_id}).scalar_one())
    out["out_of_range_confidence"] = int(session.execute(text("""
        SELECT COUNT(*) FROM article_analysis
         WHERE analysis_run_id = :rid
           AND (framing_confidence < 0 OR framing_confidence > 1)
    """), {"rid": run_id}).scalar_one())
    out["out_of_range_sentiment"] = int(session.execute(text("""
        SELECT COUNT(*) FROM article_analysis
         WHERE analysis_run_id = :rid
           AND (   headline_sentiment < -1.0 OR headline_sentiment > 1.0
                OR body_sentiment     < -1.0 OR body_sentiment     > 1.0 )
    """), {"rid": run_id}).scalar_one())
    out["invalid_framing_label"] = int(session.execute(text("""
        SELECT COUNT(*) FROM article_analysis
         WHERE analysis_run_id = :rid
           AND framing_label NOT IN
               ('critical','neutral','supportive','mixed','insufficient')
    """), {"rid": run_id}).scalar_one())
    out["duplicate_article_analysis"] = int(session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT article_id FROM article_analysis
             GROUP BY article_id HAVING COUNT(*) > 1
        ) t
    """)).scalar_one())

    # Evidence-grounding spot check — for each analysis in this run,
    # count how many evidence snippets appear verbatim in the article's
    # full_text (case-insensitive substring).
    #
    # evidence_snippets is JSONB (see ArticleAnalysis in db/models.py),
    # so use jsonb_array_length with a jsonb_typeof guard rather than
    # array_length (which is for text[]).
    verify_rows = session.execute(text("""
        SELECT aa.article_id,
               jsonb_array_length(
                    CASE jsonb_typeof(aa.evidence_snippets)
                         WHEN 'array' THEN aa.evidence_snippets
                         ELSE '[]'::jsonb END
               ) AS ev_count,
               aa.evidence_snippets,
               a.full_text
          FROM article_analysis aa
          JOIN articles a ON a.id = aa.article_id
         WHERE aa.analysis_run_id = :rid
    """), {"rid": run_id}).mappings().all()

    per_article: list[dict] = []
    total_ev = 0
    total_ev_grounded = 0
    total_qs = 0
    total_qs_grounded = 0
    for r in verify_rows:
        body = _grounding_normalize(r["full_text"] or "")
        ev = r["evidence_snippets"] or []
        grounded_ev = sum(
            1 for s in ev
            if s and _grounding_normalize(s) in body
        )
        total_ev += len(ev)
        total_ev_grounded += grounded_ev
        # Also verify quoted source quotes
        qs_row = session.execute(text("""
            SELECT quoted_sources FROM article_analysis WHERE article_id = :aid
        """), {"aid": r["article_id"]}).scalar_one()
        qs = qs_row or []
        grounded_qs = sum(
            1 for q in qs
            if isinstance(q, dict) and q.get("quote")
            and _grounding_normalize(q["quote"]) in body
        )
        total_qs += len(qs)
        total_qs_grounded += grounded_qs
        per_article.append({
            "article_id": r["article_id"],
            "evidence": {"total": len(ev), "grounded": grounded_ev},
            "quoted":   {"total": len(qs), "grounded": grounded_qs},
        })
    out["evidence_grounding"] = {
        "total_snippets": total_ev,
        "grounded":       total_ev_grounded,
        "grounding_rate": (total_ev_grounded / total_ev) if total_ev else None,
    }
    out["quoted_grounding"] = {
        "total_quotes": total_qs,
        "grounded":     total_qs_grounded,
        "grounding_rate": (total_qs_grounded / total_qs) if total_qs else None,
    }
    out["per_article_grounding"] = per_article
    return out


# ---------------------------------------------------------------------------
# Read-only diagnostic — inspect the state of one analysis_runs row.
# Used when a --run failed and we need to confirm the DB is consistent.
# ---------------------------------------------------------------------------
def check_run(run_id: int) -> int:
    """Report the current DB state around a specific analysis_runs id.

    No LLM calls. No state changes. Safe on the live database.
    Prints the run row, the article_analysis count for it, and every
    article whose ``state_updated_at`` moved since the run started (i.e.
    every article the run touched — successful or failed).
    """
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            run = conn.execute(text("""
                SELECT id, ran_at, model_id, prompt_version, purpose
                  FROM analysis_runs
                 WHERE id = :rid
            """), {"rid": run_id}).mappings().first()
            if run is None:
                print(f"analysis_runs #{run_id}: NOT FOUND")
                return 1
            print(f"analysis_runs #{run['id']}")
            print(f"  purpose        {run['purpose']}")
            print(f"  model_id       {run['model_id']!r}")
            print(f"  prompt_version {run['prompt_version']!r}")
            print(f"  ran_at         {run['ran_at']}")

            n_analyses = conn.execute(text("""
                SELECT COUNT(*) FROM article_analysis
                 WHERE analysis_run_id = :rid
            """), {"rid": run_id}).scalar_one()
            print(f"\narticle_analysis rows produced by run #{run_id}: {n_analyses}")

            # Articles whose state moved since the run started — these are
            # the articles the run actually touched (successful → analyzed
            # OR failed → attempt_count bumped and possibly failed_analyze).
            touched = conn.execute(text("""
                SELECT a.id, o.slug AS outlet, a.processing_state::text AS state,
                       a.attempt_count, a.state_updated_at,
                       LEFT(COALESCE(a.state_error, ''), 200) AS state_error
                  FROM articles a
                  JOIN outlets o ON o.id = a.outlet_id
                 WHERE a.state_updated_at >= :ran_at
                   AND a.state_updated_at <= :ran_at + INTERVAL '30 minutes'
                 ORDER BY a.id
            """), {"ran_at": run["ran_at"]}).mappings().all()

            print(f"\narticles whose state moved within +30min of the run: "
                  f"{len(touched)}")
            by_state: dict[str, int] = {}
            for a in touched:
                by_state[a["state"]] = by_state.get(a["state"], 0) + 1
            print(f"  by state: {by_state}")

            # Show at most the first 30 to keep output readable.
            for a in touched[:30]:
                print(f"  aid={a['id']:<5} outlet={a['outlet']:<18} "
                      f"state={a['state']:<16} attempts={a['attempt_count']} "
                      f"updated={a['state_updated_at']}")
                if a["state_error"]:
                    print(f"      err: {a['state_error']!r}")
            if len(touched) > 30:
                print(f"  ... ({len(touched) - 30} more not shown)")

            # Global sanity: 'analyzed' state totals in the DB right now.
            n_analyzed = conn.execute(text("""
                SELECT COUNT(*) FROM articles WHERE processing_state = 'analyzed'
            """)).scalar_one()
            n_analyses_total = conn.execute(text("""
                SELECT COUNT(*) FROM article_analysis
            """)).scalar_one()
            print(f"\nDB now: articles in 'analyzed' state = {n_analyzed}")
            print(f"DB now: article_analysis rows total    = {n_analyses_total}")
        return 0
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-check", action="store_true")
    ap.add_argument("--dry-run",   action="store_true")
    ap.add_argument("--run",       action="store_true")
    ap.add_argument("--verify",    action="store_true")
    ap.add_argument("--check-run", type=int, default=None, metavar="RUN_ID",
                    help="Read-only diagnostic on one analysis_runs id — "
                         "reports how many article_analysis rows were "
                         "produced, and the state of every article touched "
                         "since the run started. No LLM calls, no writes.")
    ap.add_argument("--target",    type=int, default=SAMPLE_TARGET,
                    help="Approx number of sample articles (default 20).")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # Silence noisy loggers from downstream libraries.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.env_check:
        return env_check()

    if args.check_run is not None:
        return check_run(args.check_run)

    if not (args.dry_run or args.run or args.verify):
        ap.print_help()
        return 2

    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)

    try:
        # --- verify last enrich run ----------------------------------------
        if args.verify:
            with Session_() as session:
                last = session.execute(
                    select(AnalysisRun)
                    .where(AnalysisRun.purpose == "enrich")
                    .order_by(AnalysisRun.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if last is None:
                    print("No enrich analysis_runs rows exist yet.")
                    return 0
                sample_ids = [
                    int(i) for i in session.execute(text("""
                        SELECT article_id FROM article_analysis
                         WHERE analysis_run_id = :rid
                    """), {"rid": last.id}).scalars().all()
                ]
                report = inspect_run(session, last.id, sample_ids)
                print_inspection(report)
                qc = data_quality_checks(session, last.id)
                print("DATA QUALITY:", json.dumps(qc, indent=2, default=str))
            return 0

        # --- select sample -------------------------------------------------
        with Session_() as session:
            sample = select_sample(session, target=args.target)
        if not sample:
            print("No eligible clustered articles to sample. Nothing to do.")
            return 1
        sample_ids = [int(r["id"]) for r in sample]
        print_sample_table(sample)

        if args.dry_run:
            print("--dry-run: skipping Groq calls.")
            return 0

        # --- real run ------------------------------------------------------
        if not settings.groq_api_key:
            print("GROQ_API_KEY is not set — refusing to run.")
            return 1
        # Sanity: model_id is set to something safe.
        print(f"model_id: {settings.llm_model!r}")
        print(f"prompt_version: {DEFAULT_PROMPT_VERSION!r}")
        print(f"about to call Groq for {len(sample_ids)} articles ...")

        started = datetime.now(tz=timezone.utc)
        with Session_() as session:
            llm = GroqClient(api_key=settings.groq_api_key)
            analyzed, failed_perm = enrich_articles(
                session,
                llm=llm,
                article_ids=sample_ids,
                batch_limit=len(sample_ids),
            )
        finished = datetime.now(tz=timezone.utc)
        dur = (finished - started).total_seconds()
        print(f"\nenrich_articles returned: analyzed={analyzed} "
              f"failed_permanent={failed_perm}  duration={dur:.1f}s")

        # --- inspect -------------------------------------------------------
        with Session_() as session:
            last = session.execute(
                select(AnalysisRun)
                .where(AnalysisRun.purpose == "enrich")
                .order_by(AnalysisRun.id.desc())
                .limit(1)
            ).scalar_one()
            report = inspect_run(session, last.id, sample_ids)
            qc = data_quality_checks(session, last.id)

        print_inspection(report)
        print("DATA QUALITY:", json.dumps(qc, indent=2, default=str))

        # --- write JSON snapshot -------------------------------------------
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path(__file__).resolve().parent / "logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"part2_enrich_{stamp}.json"
        out_path.write_text(
            json.dumps({
                "started_at":  started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_s":  dur,
                "returned":    {"analyzed": analyzed,
                                "failed_permanent": failed_perm},
                "sample_ids":  sample_ids,
                "sample_meta": sample,
                "run":         report["run"],
                "analyses":    report["analyses"],
                "unanalyzed":  report["unanalyzed"],
                "other_analyses_for_this_run": report["other_analyses_for_this_run"],
                "data_quality": qc,
            }, indent=2, default=_default),
            encoding="utf-8",
        )
        print(f"\nJSON snapshot: {out_path}")
        return 0
    finally:
        engine.dispose()


def _default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


if __name__ == "__main__":
    sys.exit(main())
