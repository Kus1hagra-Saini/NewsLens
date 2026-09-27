import { Link } from "react-router-dom";

import { StoryCard } from "@/components/story/StoryCard";
import { SectionHeader } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { IconArrowUpRight } from "@/components/ui/Icon";
import type { StorySummary } from "@/api/types";

/**
 * DISCOVER — the broader story index that gives the homepage its
 * publication weight: enough content on one page that it reads like an
 * actual news site rather than a landing page.
 *
 * Renders as a 3-column editorial grid on desktop (2 on tablet, 1 on
 * mobile) using the shared <StoryCard /> so cards match every other
 * surface. Each card has a thin top hairline instead of a floating
 * rounded rectangle — the whole grid is bound by rules, not boxes.
 */
export function Discover({
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
        kicker="Discover"
        title="More across the desk"
        subtitle="Browse recent stories across the NewsLens collection."
        action={
          stories.length > 0 ? (
            <Link
              to="/stories"
              className="group inline-flex items-center gap-1.5 rounded-sm border-b border-ink-primary/20 px-0.5 py-1 text-[11.5px] font-semibold uppercase tracking-[0.14em] text-ink-primary transition-colors hover:border-accent hover:text-accent"
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
        {isLoading ? (
          <DiscoverSkeleton />
        ) : isError ? (
          <ErrorState
            compact
            title="Couldn't load Discover"
            error={error}
            onRetry={onRetry}
          />
        ) : stories.length === 0 ? (
          <EmptyState
            title="No stories yet"
            message="Once NewsLens has clustered articles into stories, they'll show up here."
          />
        ) : (
          <div className="grid grid-cols-1 gap-x-8 gap-y-8 md:grid-cols-2 lg:grid-cols-3">
            {(() => {
              // Show an image on at most the first TWO Discover cards
              // that have a hero image. Combined with the featured
              // hero + one HotNow secondary, this keeps the Home page
              // at ~3-4 prominent images total. Cards without images
              // (or beyond the cap) fall back to the text-first look
              // that already anchors the section.
              const IMAGE_CAP = 2;
              let imagesGiven = 0;
              return stories.map((s) => {
                const canShow = imagesGiven < IMAGE_CAP && !!s.hero_image_url;
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
        )}
      </div>
    </section>
  );
}

function DiscoverSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-x-8 gap-y-8 md:grid-cols-2 lg:grid-cols-3">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="border-t border-ink-primary/15 pt-4">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="mt-2 h-5 w-3/4" />
          <Skeleton className="mt-3 h-3 w-2/3" />
          <Skeleton className="mt-2 h-3 w-1/2" />
        </div>
      ))}
    </div>
  );
}
