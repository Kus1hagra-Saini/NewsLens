import { DisclaimerFootnote } from "@/components/dashboard/DisclaimerFootnote";
import { FeaturedStory } from "@/components/story/FeaturedStory";
import { StoryCard } from "@/components/story/StoryCard";
import { SectionHeader } from "@/components/ui/Card";
import { IconInfo } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/States";
import {
  POSITIVE_STORIES_DEFAULT_LIMIT,
  usePositiveStories,
} from "@/api/queries";
import type { StorySummary } from "@/api/types";

/**
 * /positive — Positive Stories.
 *
 * Stories whose cross-outlet coverage has been predominantly positive
 * over the last few days. The backend selection rule is deterministic
 * and returns a pre-ranked ``StorySummary[]`` (see
 * ``backend/src/analysis/positive_stories.py``); this page renders that
 * list VERBATIM. No client-side re-sorting, no per-story sentiment
 * numbers, no thresholds surfaced.
 *
 * Editorial framing: "predominantly positive coverage" refers to the
 * TONE OF COVERAGE, not a judgment that any real-world event is
 * objectively good. That framing is repeated in the methodology note
 * beneath the headline so it never disappears with the scroll.
 *
 * Layout mirrors the rest of the site:
 *   - Publication masthead strip (same shape as ``/stories``,
 *     ``/outlets``) with the section eyebrow on the left and a small
 *     count on the right.
 *   - Display headline + supporting copy.
 *   - Concise inline methodology note.
 *   - When there ARE qualifying stories: the top story renders as the
 *     ``FeaturedStory`` block (inherits its "Featured coverage"
 *     kicker) and the rest fill a 3-column ``StoryCard`` grid,
 *     matching the Discover section's visual language.
 *   - When there are none: a polished editorial empty state (NOT an
 *     error), explaining that the section requires enough recent,
 *     multi-outlet analyzed coverage.
 */
export default function PositiveStories() {
  const query = usePositiveStories(POSITIVE_STORIES_DEFAULT_LIMIT);
  const stories: StorySummary[] = query.data ?? [];

  // Split for the layout below — the top story becomes the featured
  // block, the rest go into the grid. Server order is preserved.
  const featured = stories[0];
  const rest = stories.slice(1);

  return (
    <div className="flex flex-col reveal-up">
      {/* ───────────────  Masthead  ─────────────── */}
      <header>
        <div className="mb-8 flex flex-wrap items-baseline justify-between gap-y-2 border-t-2 border-ink-primary pt-3 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
          <div className="flex items-center gap-3">
            <span className="text-ink-primary">Positive Stories</span>
            <span className="hidden sm:inline text-ink-muted/50">/</span>
            <span className="hidden sm:inline">
              Predominantly positive coverage, last 7 days
            </span>
          </div>
          <div className="tabular text-ink-muted">
            {query.isLoading
              ? "Loading…"
              : query.isError
              ? "—"
              : `${stories.length} ${stories.length === 1 ? "story" : "stories"}`}
          </div>
        </div>

        <h1 className="font-display text-display-xl leading-[1.05] tracking-[-0.02em] text-ink-primary sm:text-display-2xl">
          <span>Stories with </span>
          <span className="italic text-accent">predominantly positive</span>
          <span> coverage.</span>
        </h1>
        <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-ink-secondary">
          Stories receiving predominantly positive coverage across multiple
          outlets, updated as fresh reporting arrives.
        </p>

        {/* Methodology note — deliberately small, deliberately near the
            headline so the framing travels with the section rather than
            waiting for the footer. */}
        <div className="mt-6 flex max-w-2xl items-start gap-2.5 border-l-2 border-accent/40 pl-4 text-[12.5px] leading-relaxed text-ink-muted">
          <IconInfo size={13} className="mt-[3px] shrink-0 text-accent" />
          <p>
            <span className="font-semibold text-ink-secondary">
              Positive
            </span>{" "}
            refers to the tone of coverage across outlets, not a judgment that
            an event is objectively good. Selection uses recency,
            multi-outlet coverage and article-level sentiment already computed
            during ingestion — no separate ranking of outlets.
          </p>
        </div>
      </header>

      {/* ───────────────  Feed  ─────────────── */}
      <section className="mt-14">
        {query.isLoading ? (
          <PositiveStoriesSkeleton />
        ) : query.isError ? (
          <ErrorState
            title="Couldn't load Positive Stories"
            error={query.error}
            onRetry={() => query.refetch()}
          />
        ) : stories.length === 0 ? (
          <PositiveStoriesEmpty />
        ) : (
          <>
            {/* Featured — the top of the ranked list gets the same
                treatment as the Home hero, so the eye lands on one
                clear story before scanning the grid. */}
            <FeaturedStory story={featured!} />

            {rest.length > 0 ? (
              <div className="mt-14">
                <SectionHeader
                  kicker="More positive coverage"
                  title="Other stories to read"
                  subtitle="Also seeing predominantly positive coverage across multiple outlets."
                />

                <div className="mt-6 grid grid-cols-1 gap-x-8 gap-y-8 md:grid-cols-2 lg:grid-cols-3">
                  {(() => {
                    // Reuse Discover's image policy: at most two images
                    // beyond the featured hero so the page keeps its
                    // editorial rhythm instead of turning into a grid of
                    // photos.
                    const IMAGE_CAP = 2;
                    let imagesGiven = 0;
                    return rest.map((s) => {
                      const canShow =
                        imagesGiven < IMAGE_CAP && !!s.hero_image_url;
                      if (canShow) imagesGiven += 1;
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
          </>
        )}
      </section>

      <DisclaimerFootnote />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state — this is a LEGITIMATE normal state (no qualifying stories
// right now), not an error. Uses the site's own typographic voice
// rather than the generic <EmptyState /> pill so it reads as editorial
// copy on a full-width page instead of a small placeholder.
// ---------------------------------------------------------------------------

function PositiveStoriesEmpty() {
  return (
    <div className="border-y border-ink-primary/10 py-16 text-center">
      <div className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-surface-alt text-ink-muted">
        <IconInfo size={18} />
      </div>
      <h2 className="mt-5 font-display text-display-md leading-tight text-ink-primary">
        No qualifying positive stories right now.
      </h2>
      <p className="mx-auto mt-3 max-w-lg text-[13.5px] leading-relaxed text-ink-secondary">
        This section requires enough recent, multi-outlet analyzed coverage.
        Once several outlets have covered the same story with predominantly
        positive tone, it will appear here.
      </p>
      <p className="mx-auto mt-4 max-w-lg text-[11.5px] leading-relaxed text-ink-muted">
        Check back after the next ingestion cycle.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton — matches the loaded layout so the page shape doesn't jump
// when the request lands.
// ---------------------------------------------------------------------------

function PositiveStoriesSkeleton() {
  return (
    <>
      {/* Featured skeleton — kicker + display headline + summary line +
          meta strip. Mirrors <FeaturedStory /> proportions. */}
      <div>
        <Skeleton className="h-3 w-32" />
        <Skeleton className="mt-4 h-10 w-11/12 sm:h-12" />
        <Skeleton className="mt-3 h-10 w-3/4 sm:h-12" />
        <Skeleton className="mt-6 h-4 w-4/5" />
        <Skeleton className="mt-2 h-4 w-2/3" />
        <div className="mt-6 flex gap-3">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-20" />
        </div>
      </div>

      {/* Grid skeleton — matches the 3-col ``StoryCard`` layout. */}
      <div className="mt-14">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="mt-3 h-8 w-64" />

        <div className="mt-8 grid grid-cols-1 gap-x-8 gap-y-8 md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="border-t border-ink-primary/15 pt-4">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="mt-2 h-5 w-3/4" />
              <Skeleton className="mt-3 h-3 w-2/3" />
              <Skeleton className="mt-2 h-3 w-1/2" />
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
