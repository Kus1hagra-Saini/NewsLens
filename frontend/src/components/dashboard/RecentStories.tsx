import { Link } from "react-router-dom";

import { SectionHeader } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { IconArrowUpRight } from "@/components/ui/Icon";
import { formatCount, formatRelative } from "@/lib/format";
import { useStories } from "@/api/queries";
import type { StorySummary } from "@/api/types";
import { cn } from "@/lib/cn";

/**
 * Newsroom-style feed of the most-recently-updated stories. Numbered
 * entries, headline as the primary emphasis, outlet + metadata in a
 * small caps eyebrow. Rows are separated by hairlines rather than
 * boxed in cards. Framing spread is a right-aligned data reading.
 */
export function RecentStories() {
  const query = useStories(1, 8);
  const items = query.data?.items ?? [];

  return (
    <section className="reveal-up reveal-d4">
      <SectionHeader
        kicker="Latest coverage"
        title="Stories moving across outlets"
        subtitle="Freshly-updated clusters, most recently seen first. Each entry links to the full comparative story."
        action={
          items.length > 0 ? (
            <Link
              to="/stories"
              className="group inline-flex items-center gap-1.5 rounded-sm border-b border-ink-primary/20 px-0.5 py-1 text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-primary transition-colors hover:border-accent hover:text-accent"
            >
              All stories
              <IconArrowUpRight
                size={13}
                className="transition-transform duration-200 ease-editorial group-hover:translate-x-[1px] group-hover:-translate-y-[1px]"
              />
            </Link>
          ) : null
        }
      />

      <div className="mt-6">
        {query.isLoading ? (
          <StoryListSkeleton />
        ) : query.isError ? (
          <ErrorState
            compact
            title="Couldn't load stories"
            error={query.error}
            onRetry={() => query.refetch()}
          />
        ) : items.length === 0 ? (
          <EmptyState
            title="No stories yet"
            message="Once articles cluster into stories, they'll appear here."
          />
        ) : (
          <ol className="divide-y divide-ink-primary/10 border-y border-ink-primary/10">
            {items.map((s, i) => (
              <StoryRow key={s.id} index={i + 1} story={s} />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

function StoryRow({ index, story }: { index: number; story: StorySummary }) {
  const outletCount = story.outlet_slugs?.length ?? 0;
  const primaryOutlet = story.outlet_slugs?.[0]
    ? outletSlugToLabel(story.outlet_slugs[0])
    : null;

  return (
    <li>
      <Link
        to={`/stories/${story.id}`}
        className={cn(
          "group grid grid-cols-[36px_minmax(0,1fr)_auto] items-start gap-x-5 gap-y-2",
          "py-5 pr-2",
          "transition-colors duration-150 ease-soft",
          "hover:bg-surface-alt/60",
        )}
      >
        {/* Numbered index — editorial "01, 02" style. */}
        <div className="tabular pt-0.5 text-[13px] font-semibold text-ink-muted transition-colors group-hover:text-accent">
          {index.toString().padStart(2, "0")}
        </div>

        {/* Headline + metadata line. */}
        <div className="min-w-0">
          <h3 className="font-display text-[18px] leading-snug tracking-[-0.01em] text-ink-primary transition-colors group-hover:text-accent-strong sm:text-[20px]">
            {story.title}
          </h3>

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
            {primaryOutlet ? (
              <span className="text-ink-primary">
                {primaryOutlet}
                {outletCount > 1 ? (
                  <span className="ml-1.5 font-medium normal-case tracking-normal text-ink-muted">
                    + {outletCount - 1} more
                  </span>
                ) : null}
              </span>
            ) : null}
            {story.topic ? (
              <>
                <span className="text-ink-muted/40">·</span>
                <span className="font-medium normal-case tracking-normal text-ink-secondary">
                  {story.topic}
                </span>
              </>
            ) : null}
            <span className="text-ink-muted/40">·</span>
            <span className="tabular font-medium normal-case tracking-normal">
              {formatRelative(story.last_seen_at)}
            </span>
            <span className="text-ink-muted/40">·</span>
            <span className="tabular font-medium normal-case tracking-normal">
              {formatCount(story.article_count)} article
              {story.article_count === 1 ? "" : "s"}
            </span>
          </div>
        </div>

        {/* Right-aligned data reading. */}
        <div className="flex items-center gap-3 pl-2">
          <FramingSpreadReading spread={story.framing_spread} />
          <IconArrowUpRight
            size={14}
            className="mt-0.5 text-ink-muted transition-all duration-200 ease-editorial group-hover:text-accent group-hover:translate-x-[1px] group-hover:-translate-y-[1px]"
          />
        </div>
      </Link>
    </li>
  );
}

/**
 * Data reading for a story's framing spread — the population-std-dev
 * of framing_score across articles in the story. Rendered as a small
 * label + number pair rather than a pill.
 */
function FramingSpreadReading({ spread }: { spread: number | null | undefined }) {
  const hasValue = spread !== null && spread !== undefined;

  const tone = !hasValue
    ? "text-ink-muted"
    : spread! >= 0.5
    ? "text-framing-critical"
    : spread! >= 0.25
    ? "text-accent"
    : "text-ink-secondary";

  return (
    <div
      className="hidden shrink-0 flex-col items-end md:flex"
      title="Population std-dev of framing_score across articles in this story"
    >
      <div className="text-[9.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
        Spread
      </div>
      <div className={cn("tabular font-display text-[15px] font-semibold leading-tight", tone)}>
        {hasValue ? spread!.toFixed(2) : "—"}
      </div>
    </div>
  );
}

function StoryListSkeleton() {
  return (
    <ol className="divide-y divide-ink-primary/10 border-y border-ink-primary/10">
      {[0, 1, 2, 3, 4].map((i) => (
        <li key={i} className="grid grid-cols-[36px_minmax(0,1fr)_auto] items-start gap-x-5 py-5">
          <div className="tabular pt-0.5 text-[13px] font-semibold text-ink-muted/40">
            {(i + 1).toString().padStart(2, "0")}
          </div>
          <div>
            <Skeleton className="h-4 w-3/4" />
            <div className="mt-2.5 flex gap-2">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-3 w-14" />
              <Skeleton className="h-3 w-16" />
            </div>
          </div>
          <Skeleton className="hidden h-8 w-14 md:block" />
        </li>
      ))}
    </ol>
  );
}

/**
 * Convert an outlet slug to a display label. We don't have the outlet's
 * canonical name in the stories payload — only its slug — so we
 * upper-case the slug and swap dashes for a middle-dot. When a proper
 * outlet directory lands we swap this for a lookup.
 */
function outletSlugToLabel(slug: string): string {
  return slug
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .toUpperCase();
}
