import { useMemo } from "react";

import { DisclaimerFootnote } from "@/components/dashboard/DisclaimerFootnote";
import { Discover } from "@/components/home/Discover";
import { HomeMasthead } from "@/components/home/HomeMasthead";
import { HotNow } from "@/components/home/HotNow";
import { JustUpdated } from "@/components/home/JustUpdated";
import { useHomeStories } from "@/api/queries";
import type { StorySummary } from "@/api/types";

/**
 * NewsLens editorial homepage (`/`).
 *
 * Answers, top-down:
 *   1. What stories are being covered? — MASTHEAD sets the premise
 *   2. Which stories have broad coverage? — HOT NOW (visually dominant)
 *   3. What was updated recently? — JUST UPDATED
 *   4. What else can I discover? — DISCOVER (broader story index)
 *   5. And, subtly, what does NewsLens actually claim? — the framing
 *      indicator disclaimer, verbatim, at the bottom
 *
 * Data flow:
 *   - ONE fetch of /stories (via useHomeStories, capped at 40 items)
 *   - All three sections read from the same in-memory array; the
 *     ordering for each section is derived client-side. No new backend
 *     endpoint is used or created.
 *   - Sections are disjoint on the page (a story appears at most once)
 *     so the homepage doesn't feel repetitive; the parent picks Hot
 *     Now first, then fills Just Updated / Discover from what remains.
 */
const HOT_NOW_COUNT = 8;     // 1 hero + 3 secondary + up to 4 tail rows
const JUST_UPDATED_COUNT = 6;
const DISCOVER_COUNT = 9;    // 3-col × 3-row grid on desktop

export default function Home() {
  const query = useHomeStories();
  const allStories = query.data?.items ?? [];

  const { hotNow, justUpdated, discover } = useMemo(
    () => selectHomepageSections(allStories),
    [allStories],
  );

  const isLoading = query.isLoading;
  const isError = query.isError;
  const error = query.error;
  const retry = () => {
    void query.refetch();
  };

  return (
    <div className="flex flex-col">
      <HomeMasthead />

      <div className="mt-12 md:mt-16">
        <HotNow
          stories={hotNow}
          isLoading={isLoading}
          isError={isError}
          error={error}
          onRetry={retry}
        />
      </div>

      <div className="mt-16 md:mt-20">
        <JustUpdated
          stories={justUpdated}
          isLoading={isLoading}
          isError={isError}
          error={error}
          onRetry={retry}
        />
      </div>

      <div className="mt-16 md:mt-20">
        <Discover
          stories={discover}
          isLoading={isLoading}
          isError={isError}
          error={error}
          onRetry={retry}
        />
      </div>

      {/* Small framing note near the bottom — the existing NewsLens
          disclaimer, kept verbatim. */}
      <DisclaimerFootnote />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Homepage selection — pure so it's cheap to memoise and easy to reason
// about. Not exported; the derivation is a UI concern that lives with
// its consumer.
// ---------------------------------------------------------------------------

interface HomepageSections {
  hotNow: StorySummary[];
  justUpdated: StorySummary[];
  discover: StorySummary[];
}

function selectHomepageSections(all: StorySummary[]): HomepageSections {
  if (all.length === 0) {
    return { hotNow: [], justUpdated: [], discover: [] };
  }

  // Hot Now: distinct outlet count DESC, article count DESC, last_seen DESC.
  // Everything else on the page ranks below this.
  const byBroadCoverage = [...all].sort(compareByBroadCoverage);
  const hotNow = byBroadCoverage.slice(0, HOT_NOW_COUNT);
  const hotNowIds = new Set(hotNow.map((s) => s.id));

  // Just Updated: most recent first, from what Hot Now didn't take.
  const remainderAfterHot = all.filter((s) => !hotNowIds.has(s.id));
  const byRecency = [...remainderAfterHot].sort(compareByRecency);
  const justUpdated = byRecency.slice(0, JUST_UPDATED_COUNT);
  const justUpdatedIds = new Set(justUpdated.map((s) => s.id));

  // Discover: the broader index — everything not yet on the page,
  // ordered by broad-coverage again so the visible top of the grid
  // stays product-meaningful.
  const remainderAfterUpdated = remainderAfterHot.filter(
    (s) => !justUpdatedIds.has(s.id),
  );
  const discover = [...remainderAfterUpdated]
    .sort(compareByBroadCoverage)
    .slice(0, DISCOVER_COUNT);

  return { hotNow, justUpdated, discover };
}

/**
 * distinct_outlet_count DESC, article_count DESC, last_seen DESC.
 * This is the exact ordering the Phase 2 spec calls out; kept in one
 * place so the intent is auditable.
 */
function compareByBroadCoverage(a: StorySummary, b: StorySummary): number {
  const aOutlets = a.outlet_slugs?.length ?? 0;
  const bOutlets = b.outlet_slugs?.length ?? 0;
  if (aOutlets !== bOutlets) return bOutlets - aOutlets;

  if (a.article_count !== b.article_count) {
    return b.article_count - a.article_count;
  }

  return timeOf(b.last_seen_at) - timeOf(a.last_seen_at);
}

function compareByRecency(a: StorySummary, b: StorySummary): number {
  return timeOf(b.last_seen_at) - timeOf(a.last_seen_at);
}

function timeOf(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? 0 : t;
}
