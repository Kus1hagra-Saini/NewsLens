import { FeaturedStory } from "@/components/story/FeaturedStory";
import { StoryCard } from "@/components/story/StoryCard";
import { StoryListItem } from "@/components/story/StoryListItem";
import { SectionHeader } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import type { StorySummary } from "@/api/types";

/**
 * HOT NOW — the visually dominant homepage section.
 *
 * A three-tier editorial grid:
 *   - The single most-broadly-covered story becomes the featured hero
 *   - The next 2-4 stories sit as secondary cards on the right column
 *   - Any remaining stories fall into a compact numbered list below
 *
 * Semantically we deliberately do NOT call these "the most important"
 * stories. The heading + subheading refer to "broad, recent coverage"
 * only — the ordering signal is distinct outlet count, then article
 * count, then recency. No opaque importance score, no political axis.
 *
 * The parent owns loading/error/empty semantics for the whole homepage
 * data query, so this section only renders skeletons + retries on its
 * own axis when the parent hands it a query state. Everything is
 * derived from the caller-supplied `stories` array; the parent decides
 * which subset of the /stories response counts as Hot Now.
 */
export function HotNow({
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
  return (
    <section className="reveal-up">
      <SectionHeader
        kicker="Hot now"
        title="Broadly covered right now"
        subtitle="Stories receiving broad, recent coverage across NewsLens-monitored outlets."
      />

      <div className="mt-8">
        {isLoading ? (
          <HotNowSkeleton />
        ) : isError ? (
          <ErrorState
            compact
            title="Couldn't load Hot Now"
            error={error}
            onRetry={onRetry}
          />
        ) : stories.length === 0 ? (
          <EmptyState
            title="No stories yet"
            message="Once articles cluster into stories with coverage from multiple outlets, they'll appear here."
          />
        ) : (
          <HotNowGrid stories={stories} />
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Grid — 12-col editorial layout on desktop, single column below.
// ---------------------------------------------------------------------------
function HotNowGrid({ stories }: { stories: StorySummary[] }) {
  const [featured, ...rest] = stories;
  // Secondary column: up to 3 companion stories next to the hero.
  const secondary = rest.slice(0, 3);
  // Tail: everything else, capped at 4 rows so the section stays scannable.
  const tail = rest.slice(3, 7);

  return (
    <div className="flex flex-col gap-y-10">
      {/* Row 1 — hero + secondary column */}
      <div className="grid grid-cols-1 gap-x-10 gap-y-10 lg:grid-cols-12">
        {/* Featured — 7 of 12 on desktop, full width on tablet & mobile */}
        <div className="lg:col-span-7">
          {featured ? <FeaturedStory story={featured} /> : null}
        </div>

        {/* Secondary — 5 of 12, stacked with hairline dividers.
            Only the FIRST secondary story with a hero image renders
            with an image; the rest stay text-first so the section
            doesn't reduce to a stack of pictures. */}
        {secondary.length > 0 ? (
          <div className="lg:col-span-5">
            <div className="mb-4 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
              <span className="inline-block h-[6px] w-[6px] rounded-full bg-ink-primary/40" />
              Also broadly covered
            </div>
            <div className="flex flex-col gap-y-6">
              {(() => {
                let imageGiven = false;
                return secondary.map((s) => {
                  const canShow = !imageGiven && !!s.hero_image_url;
                  if (canShow) imageGiven = true;
                  return (
                    <StoryCard
                      key={s.id}
                      story={s}
                      size="md"
                      showImage={canShow}
                    />
                  );
                });
              })()}
            </div>
          </div>
        ) : null}
      </div>

      {/* Row 2 — compact numbered tail, only when we have more items */}
      {tail.length > 0 ? (
        <div>
          <div className="mb-2 flex items-center gap-2 border-t-2 border-ink-primary/80 pt-3 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
            <span className="text-ink-primary">More coverage today</span>
          </div>
          <ol className="divide-y divide-ink-primary/10">
            {tail.map((s, i) => (
              <StoryListItem
                key={s.id}
                story={s}
                mode="numbered"
                index={i + secondary.length + 2}
              />
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton — mirrors the real hero-plus-column shape so the reveal is
// smooth once data arrives.
// ---------------------------------------------------------------------------
function HotNowSkeleton() {
  return (
    <div className="flex flex-col gap-y-10">
      <div className="grid grid-cols-1 gap-x-10 gap-y-10 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="mt-5 h-10 w-full" />
          <Skeleton className="mt-2 h-10 w-5/6" />
          <Skeleton className="mt-2 h-10 w-3/4" />
          <Skeleton className="mt-6 h-3 w-4/5" />
          <Skeleton className="mt-2 h-3 w-3/5" />
          <Skeleton className="mt-6 h-3 w-56" />
        </div>
        <div className="lg:col-span-5">
          <Skeleton className="h-3 w-40" />
          <div className="mt-4 flex flex-col gap-6">
            {[0, 1, 2].map((i) => (
              <div key={i} className="border-t border-ink-primary/15 pt-4">
                <Skeleton className="h-5 w-full" />
                <Skeleton className="mt-2 h-5 w-3/4" />
                <Skeleton className="mt-3 h-3 w-2/3" />
              </div>
            ))}
          </div>
        </div>
      </div>
      <div>
        <Skeleton className="h-3 w-40" />
        <ol className="mt-3 divide-y divide-ink-primary/10">
          {[0, 1, 2, 3].map((i) => (
            <li key={i} className="grid grid-cols-[38px_minmax(0,1fr)_auto] items-baseline gap-x-4 py-4">
              <Skeleton className="h-3 w-6" />
              <div>
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="mt-2 h-3 w-2/5" />
              </div>
              <Skeleton className="h-4 w-16" />
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
