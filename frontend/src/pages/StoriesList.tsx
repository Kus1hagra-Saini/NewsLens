import { useState } from "react";
import { Link } from "react-router-dom";

import { SectionHeader } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { DisclaimerFootnote } from "@/components/dashboard/DisclaimerFootnote";
import { IconArrowUpRight } from "@/components/ui/Icon";
import { formatCount, formatRelative } from "@/lib/format";
import { useStories } from "@/api/queries";
import type { StorySummary } from "@/api/types";
import { cn } from "@/lib/cn";

const PAGE_SIZE = 20;

/**
 * /stories — the full paginated newsroom feed.
 *
 * Reuses the editorial section language from the dashboard: masthead
 * strip, kicker + display headline, hairline dividers, numbered
 * newsroom rows. Pagination controls sit under the feed as a compact
 * data strip; the current page is derived from local state (URL
 * search params can come in Part 3 if needed).
 */
export default function StoriesList() {
  const [page, setPage] = useState(1);
  const query = useStories(page, PAGE_SIZE);

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rangeStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const rangeEnd = Math.min(page * PAGE_SIZE, total);

  return (
    <div className="flex flex-col reveal-up">
      {/* Editorial masthead */}
      <header>
        <div className="mb-8 flex flex-wrap items-baseline justify-between gap-y-2 border-t-2 border-ink-primary pt-3 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
          <div className="flex items-center gap-3">
            <span className="text-ink-primary">Stories</span>
            <span className="hidden sm:inline text-ink-muted/50">/</span>
            <span className="hidden sm:inline">Every clustered story</span>
          </div>
          <div className="tabular text-ink-muted">
            {query.isLoading ? "Loading…" : `${formatCount(total)} in total`}
          </div>
        </div>

        <h1 className="font-display text-display-xl leading-[1.05] tracking-[-0.02em] text-ink-primary sm:text-display-2xl">
          Every story we&rsquo;re tracking.
        </h1>
        <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-ink-secondary">
          Article clusters across every monitored Indian outlet, most recently
          updated first. Each entry links to a full comparative breakdown —
          article-by-article framing, coverage matrix, and where outlets
          diverge.
        </p>
      </header>

      {/* Feed */}
      <section className="mt-14">
        <SectionHeader
          kicker={query.data ? `Page ${page} of ${totalPages}` : "Feed"}
          title="The full feed"
          subtitle={
            query.data && total > 0
              ? `Showing ${rangeStart}–${rangeEnd} of ${formatCount(total)} stories.`
              : undefined
          }
        />

        <div className="mt-6">
          {query.isLoading ? (
            <FeedSkeleton />
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
                <StoryRow
                  key={s.id}
                  index={(page - 1) * PAGE_SIZE + i + 1}
                  story={s}
                />
              ))}
            </ol>
          )}
        </div>

        {/* Pagination strip — only when there's more than one page */}
        {totalPages > 1 && !query.isError ? (
          <Pagination
            page={page}
            totalPages={totalPages}
            onPrev={() => setPage((p) => Math.max(1, p - 1))}
            onNext={() =>
              setPage((p) => (query.data?.has_more ? p + 1 : Math.min(totalPages, p + 1)))
            }
            fetching={query.isFetching}
          />
        ) : null}
      </section>

      <DisclaimerFootnote />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row + helpers — shape mirrors RecentStories on the dashboard so the
// feed reads consistently across pages.
// ---------------------------------------------------------------------------
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
          "group grid grid-cols-[42px_minmax(0,1fr)_auto] items-start gap-x-5 gap-y-2",
          "py-5 pr-2",
          "transition-colors duration-150 ease-soft",
          "hover:bg-surface-alt/60",
        )}
      >
        <div className="tabular pt-0.5 text-[13px] font-semibold text-ink-muted transition-colors group-hover:text-accent">
          {index.toString().padStart(2, "0")}
        </div>

        <div className="min-w-0">
          <h3 className="font-display text-[19px] leading-snug tracking-[-0.01em] text-ink-primary transition-colors group-hover:text-accent-strong sm:text-[21px]">
            {story.title}
          </h3>

          {story.summary ? (
            <p className="mt-2 line-clamp-2 max-w-2xl text-[13.5px] leading-relaxed text-ink-secondary">
              {story.summary}
            </p>
          ) : null}

          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
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

function Pagination({
  page,
  totalPages,
  onPrev,
  onNext,
  fetching,
}: {
  page: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
  fetching: boolean;
}) {
  const prevDisabled = page <= 1 || fetching;
  const nextDisabled = page >= totalPages || fetching;

  return (
    <nav
      className="mt-6 flex items-center justify-between border-t border-ink-primary/10 pt-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted"
      aria-label="Stories pagination"
    >
      <button
        type="button"
        onClick={onPrev}
        disabled={prevDisabled}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-sm border-b border-transparent px-0.5 py-1 transition-colors",
          prevDisabled
            ? "opacity-40 cursor-not-allowed"
            : "hover:border-accent hover:text-accent",
        )}
      >
        <span aria-hidden>←</span> Previous
      </button>

      <div className="tabular flex items-center gap-2 text-ink-secondary">
        <span>
          Page <span className="text-ink-primary">{page}</span> of {totalPages}
        </span>
        {fetching ? (
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent animate-pulse-dot" />
        ) : null}
      </div>

      <button
        type="button"
        onClick={onNext}
        disabled={nextDisabled}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-sm border-b border-transparent px-0.5 py-1 transition-colors",
          nextDisabled
            ? "opacity-40 cursor-not-allowed"
            : "hover:border-accent hover:text-accent",
        )}
      >
        Next <span aria-hidden>→</span>
      </button>
    </nav>
  );
}

function FeedSkeleton() {
  return (
    <ol className="divide-y divide-ink-primary/10 border-y border-ink-primary/10">
      {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
        <li key={i} className="grid grid-cols-[42px_minmax(0,1fr)_auto] items-start gap-x-5 py-5">
          <div className="tabular pt-0.5 text-[13px] font-semibold text-ink-muted/40">
            {(i + 1).toString().padStart(2, "0")}
          </div>
          <div>
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="mt-2 h-3 w-4/5" />
            <div className="mt-3 flex gap-2">
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

function outletSlugToLabel(slug: string): string {
  return slug
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .toUpperCase();
}
