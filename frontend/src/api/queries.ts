/**
 * TanStack Query hooks — one place for cache keys, staleness, and typed
 * fetchers. Components import these hooks and never touch fetch directly.
 */

import { useQuery, keepPreviousData } from "@tanstack/react-query";

import { apiGet } from "./client";
import type {
  DashboardOverview,
  PaginatedStories,
  StoryDetail,
  StorySummary,
  TrendsResponse,
} from "./types";

export const queryKeys = {
  overview: ["overview"] as const,
  trends: (window: number) => ["trends", window] as const,
  stories: (page: number, limit: number) => ["stories", page, limit] as const,
  story: (id: number) => ["story", id] as const,
  positiveStories: (limit: number) => ["positive-stories", limit] as const,
  // Home fetches /stories with `fresh=true`; keep the cache key
  // distinct from `stories(1, HOMEPAGE_STORY_LIMIT)` so a future
  // caller that happens to request page 1 at the same limit doesn't
  // silently get Home's filtered result set.
  homeStories: (limit: number) => ["home-stories", limit] as const,
} as const;

/** Dashboard KPIs + recent-activity summary. */
export function useOverview() {
  return useQuery<DashboardOverview>({
    queryKey: queryKeys.overview,
    queryFn: () => apiGet<DashboardOverview>("/overview"),
    staleTime: 60_000,
  });
}

/** Time-series + framing distribution over the last N days. */
export function useTrends(windowDays: number) {
  return useQuery<TrendsResponse>({
    queryKey: queryKeys.trends(windowDays),
    queryFn: () => apiGet<TrendsResponse>(`/trends?window=${windowDays}`),
    staleTime: 60_000,
  });
}

/**
 * Paginated story listing.
 *
 * `keepPreviousData` on page-flips keeps the previous page visible
 * while the next one loads — no full skeleton flash. This matches the
 * editorial rhythm; the UI can still show a subtle loading dot on the
 * pagination bar.
 */
export function useStories(page = 1, limit = 8) {
  return useQuery<PaginatedStories>({
    queryKey: queryKeys.stories(page, limit),
    queryFn: () =>
      apiGet<PaginatedStories>(`/stories?page=${page}&limit=${limit}`),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

/**
 * The homepage fetches a wider window of stories once and derives
 * Hot Now, Just Updated and Discover from the same in-memory payload.
 *
 * `HOMEPAGE_STORY_LIMIT` is capped at 40 because:
 *   - 1 featured + 3 secondary + 4 tail = 8 for Hot Now
 *   - 6 for Just Updated
 *   - 9 (a 3×3 grid) for Discover
 *   - Even after de-duplication across sections, 30-ish uniques leaves
 *     headroom, and 40 is well below the backend's per-page cap.
 *
 * Freshness (Part 2): Home requests ``/stories?fresh=true``, which
 * constrains the candidate set to stories whose ``last_seen_at`` falls
 * within the backend's configured freshness window (default 72h;
 * ``HOME_FRESHNESS_HOURS``). The filter is applied server-side, the
 * frontend renders whatever list it receives — Home MUST NOT
 * re-filter or drop stories by timestamp on the client, because the
 * backend already owns the rule. Stale stories continue to appear on
 * the /stories page, which calls the same endpoint WITHOUT this flag.
 *
 * Cache key is intentionally distinct from ``stories(1, limit)`` so a
 * future caller asking for page 1 unfiltered doesn't share Home's
 * filtered payload.
 */
export const HOMEPAGE_STORY_LIMIT = 40;

export function useHomeStories() {
  return useQuery<PaginatedStories>({
    queryKey: queryKeys.homeStories(HOMEPAGE_STORY_LIMIT),
    queryFn: () =>
      apiGet<PaginatedStories>(
        `/stories?page=1&limit=${HOMEPAGE_STORY_LIMIT}&fresh=true`,
      ),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

/**
 * Positive Stories — deterministic ranked feed of stories whose
 * cross-outlet coverage has been predominantly positive over the last
 * few days. Returns the same ``StorySummary`` shape as ``/stories``
 * so cards and hooks are reused verbatim.
 *
 * Ordering is applied server-side and MUST be preserved by callers;
 * do not sort the returned list on the client.
 *
 * The default limit matches the backend's ``DEFAULT_LIMIT`` (12) and
 * is safely under the server-side cap of 40.
 */
export const POSITIVE_STORIES_DEFAULT_LIMIT = 12;

export function usePositiveStories(limit: number = POSITIVE_STORIES_DEFAULT_LIMIT) {
  return useQuery<StorySummary[]>({
    queryKey: queryKeys.positiveStories(limit),
    queryFn: () => apiGet<StorySummary[]>(`/positive-stories?limit=${limit}`),
    staleTime: 60_000,
  });
}

/**
 * Single-story detail — articles, comparison and analysis. `enabled`
 * guards against firing when the id parameter is missing or NaN.
 */
export function useStoryDetail(id: number | null | undefined) {
  const numericId = typeof id === "number" && Number.isFinite(id) ? id : null;
  return useQuery<StoryDetail>({
    queryKey: numericId !== null ? queryKeys.story(numericId) : ["story", "invalid"],
    queryFn: () => apiGet<StoryDetail>(`/stories/${numericId}`),
    enabled: numericId !== null,
    staleTime: 60_000,
  });
}
