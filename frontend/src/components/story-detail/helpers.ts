/**
 * Shared helpers for the Story Detail page.
 *
 * Every helper here is pure and side-effect free so the section
 * components can memoise their results and stay easy to reason about
 * in isolation. Nothing here touches React.
 *
 * Two design commitments run through the file:
 *
 *   1. Defensive input handling. Enrichment / Compare payloads are
 *      LLM-produced. Even with strict Pydantic schemas on the backend,
 *      legacy analyses and edge cases can drift from the ideal shape.
 *      Every helper accepts the loosest reasonable input and produces a
 *      typed, safe output that section components can render without
 *      further guards.
 *
 *   2. Non-political vocabulary. Framing indicators describe article-
 *      level tone toward the primary subject (critical / neutral /
 *      supportive). None of this file introduces political labels such
 *      as Left / Right — those are the responsibility of the (deferred)
 *      Media Bias Bar and its externally-sourced publication-level data.
 */

import type {
  ArticleAnalysisPayload,
  ArticleInStory,
  Entities,
  QuotedSource,
  SourceDistribution,
} from "@/api/types";
import type { FramingLabel } from "@/lib/constants";

// ---------------------------------------------------------------------------
// Framing aggregation
// ---------------------------------------------------------------------------

export interface OutletFramingRow {
  slug: string;
  name: string;
  meanScore: number | null;
  count: number;
  /** Number of analyzed articles that produced a framing score. */
  scoredCount: number;
  /** Mean confidence across analyzed articles, when available. */
  meanConfidence: number | null;
  /** Bucketed label derived from meanScore. */
  bucket: FramingLabel | null;
  /** All raw scores contributing to this outlet's mean. */
  scores: number[];
}

/**
 * Group articles by outlet and compute the outlet-level framing summary.
 *
 * Sort order: outlets that produced at least one framing score first,
 * then outlets without any framing signal. Within each group we sort
 * alphabetically by outlet name so the ordering is stable regardless
 * of which articles the backend returned first.
 */
export function aggregateFramingByOutlet(
  articles: ArticleInStory[],
): OutletFramingRow[] {
  interface Bucket {
    name: string;
    scores: number[];
    confidences: number[];
    total: number;
  }
  const buckets = new Map<string, Bucket>();

  for (const a of articles) {
    const slug = a.outlet?.slug ?? String(a.outlet?.id ?? "unknown");
    const name = a.outlet?.name ?? slug;
    const entry: Bucket =
      buckets.get(slug) ?? { name, scores: [], confidences: [], total: 0 };
    entry.total += 1;

    const score = a.analysis?.framing_score;
    if (typeof score === "number" && Number.isFinite(score)) {
      entry.scores.push(score);
    }
    const confidence = a.analysis?.framing_confidence;
    if (typeof confidence === "number" && Number.isFinite(confidence)) {
      entry.confidences.push(confidence);
    }
    buckets.set(slug, entry);
  }

  return [...buckets.entries()]
    .map(([slug, b]) => {
      const mean =
        b.scores.length > 0
          ? b.scores.reduce((s, v) => s + v, 0) / b.scores.length
          : null;
      const meanConf =
        b.confidences.length > 0
          ? b.confidences.reduce((s, v) => s + v, 0) / b.confidences.length
          : null;
      return {
        slug,
        name: b.name,
        count: b.total,
        scoredCount: b.scores.length,
        meanScore: mean,
        meanConfidence: meanConf,
        bucket: bucketFor(mean),
        scores: b.scores,
      };
    })
    .sort((a, b) => {
      if ((a.meanScore === null) !== (b.meanScore === null)) {
        return a.meanScore === null ? 1 : -1;
      }
      return a.name.localeCompare(b.name);
    });
}

/** Bucket a mean framing score into the framing-label taxonomy. */
export function bucketFor(score: number | null): FramingLabel | null {
  if (score === null || !Number.isFinite(score)) return null;
  if (score <= -0.15) return "critical";
  if (score >= 0.15) return "supportive";
  return "neutral";
}

/**
 * Population standard deviation across a list of framing scores.
 * Deterministic, mirrors the backend framing-spread computation.
 * Returns null when there aren't at least two data points to spread.
 */
export function framingSpreadFrom(scores: number[]): number | null {
  const clean = scores.filter((s) => typeof s === "number" && Number.isFinite(s));
  if (clean.length < 2) return null;
  const mean = clean.reduce((s, v) => s + v, 0) / clean.length;
  const variance =
    clean.reduce((s, v) => s + (v - mean) * (v - mean), 0) / clean.length;
  return Math.sqrt(variance);
}

// ---------------------------------------------------------------------------
// Coverage matrix / free-form dict normalisation
// ---------------------------------------------------------------------------

/** A weighted theme surfaced by an outlet (0.0 to 1.0 emphasis). */
export interface EmphasisItem {
  label: string;
  weight: number | null;
}

export interface OutletEmphasisRow {
  slug: string;
  name: string;
  themes: EmphasisItem[];
  /** Optional supporting evidence taken from that outlet's articles. */
  supportingEvidence: string[];
}

/**
 * Turn a coverage-matrix dict from the LLM into a rendering-friendly
 * list of outlets and their themes, plus supporting evidence pulled
 * from that outlet's article-level analyses.
 *
 * Shapes we tolerate for each outlet's cell:
 *   { theme: 0.72, theme2: 0.51 }        — canonical
 *   [ "theme", "theme2" ]                — legacy string list
 *   { themes: [...] } / { items: [...] } — nested single-key wrapper
 *   "single theme"                       — degenerate scalar
 *
 * The outlet key in the matrix is a slug; when we can resolve it to an
 * outlet we surface the display name too. Unknown slugs fall back to
 * a prettified version of the key.
 */
export function outletsEmphasisFromMatrix(
  matrix: Record<string, unknown> | null,
  articles: ArticleInStory[],
): OutletEmphasisRow[] {
  if (!matrix) return [];

  const outletsBySlug = new Map<string, { name: string; evidence: string[] }>();
  for (const a of articles) {
    const slug = a.outlet?.slug;
    if (!slug) continue;
    const entry =
      outletsBySlug.get(slug) ?? { name: a.outlet?.name ?? slug, evidence: [] };
    for (const snippet of a.analysis?.evidence_snippets ?? []) {
      if (typeof snippet === "string" && snippet.trim()) {
        entry.evidence.push(snippet.trim());
      }
    }
    outletsBySlug.set(slug, entry);
  }

  const rows: OutletEmphasisRow[] = [];

  for (const [rawKey, rawValue] of Object.entries(matrix)) {
    const key = rawKey.trim();
    const themes = themesFromCell(rawValue);
    const resolved = outletsBySlug.get(key);
    rows.push({
      slug: key,
      name: resolved?.name ?? prettifyKey(key),
      themes,
      supportingEvidence: resolved?.evidence ?? [],
    });
  }

  // Order by number of weighted themes (informative outlets first),
  // then alphabetically for stability.
  return rows.sort((a, b) => {
    if (a.themes.length !== b.themes.length) {
      return b.themes.length - a.themes.length;
    }
    return a.name.localeCompare(b.name);
  });
}

function themesFromCell(value: unknown): EmphasisItem[] {
  // Weighted map: { theme: 0.7, ... }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    // Nested wrappers: prefer the inner list under a familiar key.
    for (const preferred of ["themes", "items", "points", "highlights"]) {
      if (Array.isArray(obj[preferred])) {
        return themesFromCell(obj[preferred]);
      }
    }
    const items: EmphasisItem[] = [];
    for (const [k, v] of Object.entries(obj)) {
      const label = String(k).trim();
      if (!label) continue;
      items.push({ label, weight: coerceWeight(v) });
    }
    return items.sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0));
  }
  // Simple string list: [ "theme", ... ]
  if (Array.isArray(value)) {
    return value
      .map((v) => (typeof v === "string" ? v.trim() : ""))
      .filter((s) => s.length > 0)
      .map((label) => ({ label, weight: null }));
  }
  // Degenerate scalar.
  if (typeof value === "string" && value.trim()) {
    return [{ label: value.trim(), weight: null }];
  }
  return [];
}

function coerceWeight(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.max(0, Math.min(1, v));
  }
  if (typeof v === "string") {
    const n = Number(v);
    if (Number.isFinite(n)) return Math.max(0, Math.min(1, n));
  }
  return null;
}

// ---------------------------------------------------------------------------
// Coverage gaps ("not present here") normalisation
// ---------------------------------------------------------------------------

export interface CoverageGapRow {
  slug: string;
  name: string;
  items: string[];
}

/**
 * Normalise ``not_present_here`` into rendering-ready rows keyed by
 * outlet slug. We resolve the display name from the article list when
 * we can; otherwise we fall back to a prettified slug.
 */
export function coverageGapsFromMatrix(
  matrix: Record<string, unknown> | null,
  articles: ArticleInStory[],
): CoverageGapRow[] {
  if (!matrix) return [];

  const nameBySlug = new Map<string, string>();
  for (const a of articles) {
    if (a.outlet?.slug) nameBySlug.set(a.outlet.slug, a.outlet.name);
  }

  const rows: CoverageGapRow[] = [];
  for (const [rawKey, value] of Object.entries(matrix)) {
    const slug = rawKey.trim();
    rows.push({
      slug,
      name: nameBySlug.get(slug) ?? prettifyKey(slug),
      items: valueToStringList(value),
    });
  }
  return rows.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Generic "convert an LLM cell into a readable list of strings". Kept
 * here as a shared fallback so multiple sections agree on how a
 * ragged dict is rendered.
 */
export function valueToStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((v) => {
        if (typeof v === "string") return v.trim();
        if (v && typeof v === "object") return JSON.stringify(v);
        return String(v);
      })
      .filter((s) => s.length > 0);
  }
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    for (const preferred of ["items", "themes", "points", "highlights"]) {
      if (Array.isArray(obj[preferred])) return valueToStringList(obj[preferred]);
    }
    return Object.entries(obj).map(
      ([k, v]) =>
        `${prettifyKey(k)}: ${typeof v === "string" ? v : JSON.stringify(v)}`,
    );
  }
  if (typeof value === "string") return value.trim() ? [value.trim()] : [];
  if (value === null || value === undefined) return [];
  return [String(value)];
}

export function prettifyKey(key: string): string {
  return key
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Framing label normalisation
// ---------------------------------------------------------------------------

export function normaliseFramingLabel(
  label: string | null | undefined,
): FramingLabel | null {
  if (!label) return null;
  const lower = label.trim().toLowerCase();
  if (
    lower === "critical" ||
    lower === "neutral" ||
    lower === "supportive" ||
    lower === "mixed" ||
    lower === "insufficient" ||
    lower === "unlabeled"
  ) {
    return lower as FramingLabel;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Source (quoted-source + distribution) aggregation
// ---------------------------------------------------------------------------

/** Canonical categories the backend SourceDistribution schema uses. */
export const SOURCE_CATEGORIES = [
  "government",
  "opposition",
  "expert",
  "civil_society",
  "corporate",
  "unnamed_source",
  "other",
] as const;

export type SourceCategory = (typeof SOURCE_CATEGORIES)[number];

export const SOURCE_CATEGORY_LABELS: Record<SourceCategory, string> = {
  government: "Government",
  opposition: "Opposition",
  expert: "Experts",
  civil_society: "Civil society",
  corporate: "Corporate",
  unnamed_source: "Unnamed",
  other: "Other",
};

export interface OutletSourceBreakdown {
  slug: string;
  name: string;
  totals: Record<SourceCategory, number>;
  total: number;
}

/**
 * Sum `source_distribution` counts across all analyses for each outlet.
 * Missing categories default to zero. Unknown categories are folded
 * into "other" rather than dropped, so the total stays honest.
 */
export function aggregateSourceDistribution(
  articles: ArticleInStory[],
): OutletSourceBreakdown[] {
  const buckets = new Map<string, OutletSourceBreakdown>();

  for (const a of articles) {
    const slug = a.outlet?.slug ?? String(a.outlet?.id ?? "unknown");
    const name = a.outlet?.name ?? slug;
    const entry: OutletSourceBreakdown =
      buckets.get(slug) ?? {
        slug,
        name,
        totals: emptyTotals(),
        total: 0,
      };

    const dist = a.analysis?.source_distribution as
      | SourceDistribution
      | Record<string, unknown>
      | null
      | undefined;

    if (dist && typeof dist === "object") {
      for (const [rawKey, rawValue] of Object.entries(dist)) {
        const category = resolveCategory(rawKey);
        const n = coerceNonNegativeInt(rawValue);
        if (n === null) continue;
        entry.totals[category] += n;
        entry.total += n;
      }
    }

    buckets.set(slug, entry);
  }

  return [...buckets.values()].sort((a, b) => {
    if (a.total !== b.total) return b.total - a.total;
    return a.name.localeCompare(b.name);
  });
}

/**
 * Sum a specific category across all outlets in the story, for the
 * cross-outlet "who's being heard" comparison bars.
 */
export function totalsBycategoryAcrossOutlets(
  rows: OutletSourceBreakdown[],
): Record<SourceCategory, number> {
  const out = emptyTotals();
  for (const r of rows) {
    for (const cat of SOURCE_CATEGORIES) {
      out[cat] += r.totals[cat];
    }
  }
  return out;
}

function emptyTotals(): Record<SourceCategory, number> {
  return {
    government: 0,
    opposition: 0,
    expert: 0,
    civil_society: 0,
    corporate: 0,
    unnamed_source: 0,
    other: 0,
  };
}

function resolveCategory(key: string): SourceCategory {
  const normalised = key.trim().toLowerCase().replace(/[\s-]+/g, "_");
  return (SOURCE_CATEGORIES as readonly string[]).includes(normalised)
    ? (normalised as SourceCategory)
    : "other";
}

function coerceNonNegativeInt(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) {
    return Math.max(0, Math.round(v));
  }
  if (typeof v === "string") {
    const n = Number(v);
    if (Number.isFinite(n)) return Math.max(0, Math.round(n));
  }
  return null;
}

// ---------------------------------------------------------------------------
// Quoted sources
// ---------------------------------------------------------------------------

/** A well-formed quoted source ready for rendering. */
export interface CleanQuotedSource {
  speaker: string;
  affiliation: string | null;
  quote: string;
  stance: "supports" | "criticizes" | "neutral" | "unclear" | "unknown";
  outletSlug: string;
  outletName: string;
}

/**
 * Flatten every article's quoted_sources into a single list of
 * cleanly-typed records, ready to group or filter in the UI. Legacy
 * string-only entries and rows that lack a quote are dropped, because
 * they don't render as anything a reader can trust.
 */
export function collectQuotedSources(
  articles: ArticleInStory[],
): CleanQuotedSource[] {
  const out: CleanQuotedSource[] = [];

  for (const a of articles) {
    const outletSlug = a.outlet?.slug ?? String(a.outlet?.id ?? "unknown");
    const outletName = a.outlet?.name ?? outletSlug;
    const raw = a.analysis?.quoted_sources;
    if (!Array.isArray(raw)) continue;

    for (const entry of raw) {
      if (!entry) continue;
      if (typeof entry === "string") {
        // Legacy shape: whole quote-with-attribution in one string.
        const trimmed = entry.trim();
        if (!trimmed) continue;
        out.push({
          speaker: "Unattributed",
          affiliation: null,
          quote: stripQuotes(trimmed),
          stance: "unknown",
          outletSlug,
          outletName,
        });
        continue;
      }
      if (typeof entry !== "object") continue;

      const obj = entry as QuotedSource;
      const quote = typeof obj.quote === "string" ? obj.quote.trim() : "";
      if (!quote) continue;

      const speakerRaw = typeof obj.speaker === "string" ? obj.speaker.trim() : "";
      const affRaw =
        typeof obj.affiliation === "string" ? obj.affiliation.trim() : "";
      const stanceRaw = typeof obj.stance === "string" ? obj.stance.trim().toLowerCase() : "";

      out.push({
        speaker: speakerRaw || "Unattributed",
        affiliation: affRaw || null,
        quote: stripQuotes(quote),
        stance: canonicaliseStance(stanceRaw),
        outletSlug,
        outletName,
      });
    }
  }
  return out;
}

function canonicaliseStance(
  raw: string,
): CleanQuotedSource["stance"] {
  if (raw === "supports" || raw === "support" || raw === "supportive") return "supports";
  if (raw === "criticizes" || raw === "critical" || raw === "criticises") return "criticizes";
  if (raw === "neutral") return "neutral";
  if (raw === "unclear" || raw === "mixed") return "unclear";
  return "unknown";
}

function stripQuotes(s: string): string {
  return s.replace(/^["“”'‘’]+|["“”'‘’]+$/g, "").trim();
}

// ---------------------------------------------------------------------------
// Entities
// ---------------------------------------------------------------------------

export interface EntitiesRollup {
  people: string[];
  organizations: string[];
  locations: string[];
  other: string[];
}

/**
 * Merge and de-duplicate entities across every analysis on a story.
 * Case-insensitive de-duplication; the first-seen casing wins.
 */
export function rollupEntities(articles: ArticleInStory[]): EntitiesRollup {
  const seen: Record<keyof EntitiesRollup, Map<string, string>> = {
    people: new Map(),
    organizations: new Map(),
    locations: new Map(),
    other: new Map(),
  };

  for (const a of articles) {
    const ent = a.analysis?.entities as Entities | Record<string, unknown> | null | undefined;
    if (!ent || typeof ent !== "object") continue;
    for (const key of Object.keys(seen) as (keyof EntitiesRollup)[]) {
      const list = (ent as Record<string, unknown>)[key];
      if (!Array.isArray(list)) continue;
      for (const v of list) {
        if (typeof v !== "string") continue;
        const trimmed = v.trim();
        if (!trimmed) continue;
        const k = trimmed.toLowerCase();
        if (!seen[key].has(k)) seen[key].set(k, trimmed);
      }
    }
  }

  return {
    people: [...seen.people.values()],
    organizations: [...seen.organizations.values()],
    locations: [...seen.locations.values()],
    other: [...seen.other.values()],
  };
}

/**
 * Same rollup, but scoped to a single article's payload. Small helper
 * so ArticleCard can render its own tight entity strip without the
 * story-wide dedupe pipeline.
 */
export function entitiesFromPayload(
  analysis: ArticleAnalysisPayload | null,
): EntitiesRollup {
  if (!analysis) {
    return { people: [], organizations: [], locations: [], other: [] };
  }
  const ent = analysis.entities as Entities | Record<string, unknown> | null;
  const pick = (k: string): string[] => {
    if (!ent || typeof ent !== "object") return [];
    const v = (ent as Record<string, unknown>)[k];
    if (!Array.isArray(v)) return [];
    return v.filter((x): x is string => typeof x === "string" && x.trim().length > 0);
  };
  return {
    people: pick("people"),
    organizations: pick("organizations"),
    locations: pick("locations"),
    other: pick("other"),
  };
}

// ---------------------------------------------------------------------------
// Article grouping (by outlet)
// ---------------------------------------------------------------------------

export interface OutletArticleGroup {
  slug: string;
  name: string;
  website: string;
  articles: ArticleInStory[];
}

/**
 * Group a story's articles by outlet, with each outlet's articles
 * sorted newest-first inside the group and the outlets themselves
 * ordered by their most recent article across all articles they own.
 */
export function groupArticlesByOutlet(
  articles: ArticleInStory[],
): OutletArticleGroup[] {
  const groups = new Map<string, OutletArticleGroup>();

  for (const a of articles) {
    const slug = a.outlet?.slug ?? String(a.outlet?.id ?? "unknown");
    const name = a.outlet?.name ?? slug;
    const website = a.outlet?.website ?? "";
    const g: OutletArticleGroup =
      groups.get(slug) ?? { slug, name, website, articles: [] };
    g.articles.push(a);
    groups.set(slug, g);
  }

  for (const g of groups.values()) {
    g.articles.sort(
      (a, b) => timeOf(b.published_at) - timeOf(a.published_at),
    );
  }

  return [...groups.values()].sort((a, b) => {
    const aMax = Math.max(0, ...a.articles.map((x) => timeOf(x.published_at)));
    const bMax = Math.max(0, ...b.articles.map((x) => timeOf(x.published_at)));
    if (aMax !== bMax) return bMax - aMax;
    return a.name.localeCompare(b.name);
  });
}

// ---------------------------------------------------------------------------
// Time helpers
// ---------------------------------------------------------------------------

export function timeOf(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? 0 : t;
}
