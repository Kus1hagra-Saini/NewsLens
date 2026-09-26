import { StoryListItem } from "@/components/story/StoryListItem";
import { SectionHeader } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import type { StorySummary } from "@/api/types";

/**
 * JUST UPDATED — editorial list of the most recently updated stories.
 *
 * Sorted client-side by `last_seen_at DESC` in the parent. The row
 * component leads with a relative-time chip in the accent colour so
 * the eye scans down the freshness axis rather than an outlet count.
 *
 * On desktop the list splits into two columns so the section reads
 * as a broadsheet "briefing" panel rather than a long scroll; on
 * mobile it collapses to a single column feed.
 */
export function JustUpdated({
  stories,
  isLoading,
  isError,
  error,
  onRetry,
}: {
  stories: StorySummary[];
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  onRetry?: () => void;
}) {
  // Split into two roughly-even columns for the desktop layout.
  const mid = Math.ceil(stories.length / 2);
  const left = stories.slice(0, mid);
  const right = stories.slice(mid);

  return (
    <section className="reveal-up">
      <SectionHeader
        kicker="Just updated"
        title="Fresh across outlets"
        subtitle="Stories with the latest coverage, most recently seen first."
      />

      <div className="mt-6">
        {isLoading ? (
          <JustUpdatedSkeleton />
        ) : isError ? (
          <ErrorState
            compact
            title="Couldn't load Just Updated"
            error={error}
            onRetry={onRetry}
          />
        ) : stories.length === 0 ? (
          <EmptyState
            title="No recent updates"
            message="Once fresh articles are ingested, they'll appear here."
          />
        ) : (
          <div className="grid grid-cols-1 gap-x-10 md:grid-cols-2">
            <ol className="divide-y divide-ink-primary/10 border-t border-ink-primary/10">
              {left.map((s) => (
                <StoryListItem key={s.id} story={s} mode="time" />
              ))}
            </ol>
            {right.length > 0 ? (
              <ol className="divide-y divide-ink-primary/10 border-t border-ink-primary/10 md:border-t md:border-ink-primary/10">
                {right.map((s) => (
                  <StoryListItem key={s.id} story={s} mode="time" />
                ))}
              </ol>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}

function JustUpdatedSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-x-10 md:grid-cols-2">
      {[0, 1].map((col) => (
        <ol
          key={col}
          className="divide-y divide-ink-primary/10 border-t border-ink-primary/10"
        >
          {[0, 1, 2].map((i) => (
            <li
              key={i}
              className="grid grid-cols-[90px_minmax(0,1fr)_auto] items-baseline gap-x-4 py-4"
            >
              <Skeleton className="h-3 w-16" />
              <div>
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="mt-2 h-3 w-1/3" />
              </div>
              <Skeleton className="h-4 w-16" />
            </li>
          ))}
        </ol>
      ))}
    </div>
  );
}
