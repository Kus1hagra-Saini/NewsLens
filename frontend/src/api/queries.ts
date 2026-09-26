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
  TrendsResponse,
} from "./types";

export const queryKeys = {
  overview: ["overview"] as const,
  trends: (window: number) => ["trends", window] as const,
  stories: (page: number, limit: number) => ["stories", page, limit] as const,
  story: (id: number) => ["story", id] as const,
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
 * This is intentionally a thin wrapper around ``useStories`` so it
 * shares TanStack's cache with anything else that requests the same
 * page+limit pair (no duplicate network calls).
 *
 * `HOMEPAGE_STORY_LIMIT` is capped at 40 because:
 *   - 1 featured + 3 secondary + 4 tail = 8 for Hot Now
 *   - 6 for Just Updated
 *   - 9 (a 3×3 grid) for Discover
 *   - Even after de-duplication across sections, 30-ish uniques leaves
 *     headroom, and 40 is well below the backend's per-page cap.
 *
 * If the backend later enforces a smaller limit we can lower this
 * without any component changes.
 */
export const HOMEPAGE_STORY_LIMIT = 40;

export function useHomeStories() {
  return useStories(1, HOMEPAGE_STORY_LIMIT);
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
