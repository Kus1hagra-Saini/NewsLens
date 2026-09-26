/**
 * TypeScript mirrors of the backend Pydantic response schemas
 * (see backend/src/api/schemas.py). Only fields the frontend actually
 * uses are declared here to keep the surface small.
 *
 * Defensive typing: LLM output can, on rare occasions, drift from the
 * strict Pydantic contract (older analyses, partial runs). Every field
 * on the analysis / comparison payloads is therefore modelled as
 * optional or nullable, and callers should treat every property as
 * possibly-missing at render time.
 */

export interface OutletSummary {
  id: number;
  name: string;
  slug: string;
  website: string;
  logo_url: string | null;
}

export interface OutletDetail extends OutletSummary {
  rss_url: string;
  active: boolean;
}

export interface LatestIngestionRun {
  id: number;
  started_at: string;
  completed_at: string | null;
  status: "running" | "success" | "failed" | "skipped";
  articles_discovered: number;
  articles_inserted: number;
  articles_failed: number;
  llm_calls: number;
}

export interface DashboardOverview {
  article_count: number;
  story_count: number;
  active_outlet_count: number;
  articles_by_state: Record<string, number>;
  articles_last_24h: number;
  stories_last_24h: number;
  latest_ingestion_run: LatestIngestionRun | null;
  framing_distribution: Record<string, number>;
  framing_disclaimer: string;
}

export interface TimeSeriesPoint {
  date: string; // YYYY-MM-DD
  count: number;
}

export interface FramingBucket {
  label: string;
  count: number;
}

export interface TrendsResponse {
  window_days: number;
  articles_per_day: TimeSeriesPoint[];
  stories_per_day: TimeSeriesPoint[];
  framing_distribution: FramingBucket[];
  framing_disclaimer: string;
}

export interface StorySummary {
  id: number;
  title: string;
  topic: string | null;
  first_seen_at: string;
  last_seen_at: string;
  article_count: number;
  summary: string | null;
  outlet_slugs: string[];
  framing_spread: number | null;
}

export interface PaginatedStories {
  items: StorySummary[];
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
}

// ---------------------------------------------------------------------------
// Story detail — /stories/{id}
// ---------------------------------------------------------------------------

/**
 * Named-entity groups extracted by Enrichment. Mirrors the backend
 * ``Entities`` Pydantic model but every bucket is optional so the
 * frontend renders gracefully on older analyses that lack a bucket.
 */
export interface Entities {
  people?: string[];
  organizations?: string[];
  locations?: string[];
  other?: string[];
}

/**
 * The extracted stance label attached to a quoted source. Mirrors
 * the backend enum (supports / criticizes / neutral / unclear) but a
 * plain string is accepted as fallback so an unfamiliar label doesn't
 * crash the UI.
 */
export type QuotedSourceStance =
  | "supports"
  | "criticizes"
  | "neutral"
  | "unclear"
  | string;

/**
 * One attributed quote. Mirrors the backend ``QuotedSource`` schema.
 * Every field is optional/nullable so a partially-formed record still
 * renders — the component can decide what to show and what to hide.
 */
export interface QuotedSource {
  speaker?: string | null;
  affiliation?: string | null;
  quote?: string | null;
  stance?: QuotedSourceStance | null;
}

/**
 * Counts of sources by category. Mirrors the backend
 * ``SourceDistribution`` Pydantic model. All fields optional to allow
 * partial rendering when a category is missing.
 */
export interface SourceDistribution {
  government?: number;
  opposition?: number;
  expert?: number;
  civil_society?: number;
  corporate?: number;
  unnamed_source?: number;
  other?: number;
}

/**
 * Article-level LLM analysis. Every field is nullable / possibly-empty
 * because Enrichment can leave some cells blank (insufficient signal,
 * partial run) and the UI must render gracefully in that case.
 *
 * `quoted_sources` accepts either the current structured object form or
 * a raw string, because older analyses may still exist in the database
 * with the pre-v2 flat-string shape.
 */
export interface ArticleAnalysisPayload {
  framing_score: number | null;
  framing_label: string | null;
  framing_confidence: number | null;
  headline_sentiment: number | null;
  body_sentiment: number | null;
  key_themes: string[];
  entities: Entities | Record<string, unknown> | null;
  quoted_sources: Array<QuotedSource | string> | null;
  source_distribution: SourceDistribution | Record<string, unknown> | null;
  evidence_snippets: string[];
  analyzed_at: string;
}

export interface ArticleInStory {
  id: number;
  outlet: OutletSummary;
  url: string;
  headline: string;
  author: string | null;
  published_at: string;
  processing_state: string;
  analysis: ArticleAnalysisPayload | null;
}

/**
 * Cross-article comparison. Written by Compare (arch §7). The
 * `differences` field is a paragraph of editorial prose. Matrix
 * shapes are free-form dicts from the LLM.
 */
export interface StoryComparisonPayload {
  differences: string;
  framing_spread: number | null;
  coverage_matrix: Record<string, unknown> | null;
  not_present_here: Record<string, unknown> | null;
  generated_at: string;
}

// ---------------------------------------------------------------------------
// Media Bias Distribution (publication-level, external ratings)
//
// This is NOT NewsLens's article-level framing. It describes the
// distribution of documented publication-level bias ratings for the
// OUTLETS covering a story — never for the story itself or its
// articles. The backend computes and returns this payload; the
// frontend renders it verbatim.
// ---------------------------------------------------------------------------

export type BiasCategory = "left" | "center" | "right";

export type BiasDistributionReason =
  | "too_few_outlets"        // <3 distinct outlets in the story
  | "too_few_rated_outlets"; // <3 rated outlets covering the story

export interface BiasDistributionSource {
  outlet_id: number;
  outlet_slug: string;
  outlet_name: string;
  /** Verbatim external label, e.g. "Left-Center" from MBFC. */
  original_rating: string;
  /** Deterministic bucket used by the visualisation. */
  normalized_category: BiasCategory;
  /** External rating org: "MBFC", "AdFontes", etc. */
  rating_source: string;
  rating_url: string;
  /** ISO timestamp of the external source's last update, when known. */
  rated_at: string | null;
}

export interface BiasDistribution {
  eligible: boolean;
  reason: BiasDistributionReason | null;
  total_outlet_count: number;
  rated_outlet_count: number;
  unrated_outlet_count: number;
  unrated_outlet_slugs: string[];
  /** Percentage per bucket; sums to ~100 (subject to rounding). */
  distribution: Record<BiasCategory, number>;
  /** Raw counts per bucket. */
  counts: Record<BiasCategory, number>;
  sources: BiasDistributionSource[];
}

export interface StoryDetail extends StorySummary {
  articles: ArticleInStory[];
  comparison: StoryComparisonPayload | null;
  bias_distribution: BiasDistribution | null;
  framing_disclaimer: string;
}
