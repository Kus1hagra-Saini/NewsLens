import { Link } from "react-router-dom";

import { CompactBiasBar } from "@/components/story-detail/CompactBiasBar";
import { IconArrowUpRight } from "@/components/ui/Icon";
import type { StorySummary } from "@/api/types";
import { cn } from "@/lib/cn";
import { StoryMeta } from "./StoryMeta";

/**
 * The Hot Now hero — a single large editorial block that anchors the
 * homepage. The headline is set in Fraunces at display scale so the
 * top of the page reads unmistakably as a publication front page.
 *
 * No image, no card chrome. Just a small kicker, an enormous headline,
 * a short summary excerpt, and the outlet-count-forward metadata line.
 * The whole block is a link to the story detail. The component is
 * structured so an optional lead image can slot in later (a plain
 * <figure> above the kicker) without redesigning anything else.
 */
export function FeaturedStory({
  story,
  className,
}: {
  story: StorySummary;
  className?: string;
}) {
  return (
    <article className={cn("group relative", className)}>
      <Link
        to={`/stories/${story.id}`}
        className="block outline-none focus-visible:ring-0"
      >
        {/* Kicker line — behaves like a section eyebrow on the front page. */}
        <div className="mb-4 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-accent">
          <span className="inline-block h-[6px] w-[6px] rounded-full bg-accent" />
          Featured coverage
        </div>

        <h3
          className={cn(
            "font-display text-ink-primary",
            "text-[32px] leading-[1.08] tracking-[-0.02em]",
            "sm:text-[38px] md:text-[44px] lg:text-[48px]",
            "transition-colors duration-150 ease-editorial",
            "group-hover:text-accent-strong",
          )}
        >
          {story.title}
        </h3>

        {story.summary ? (
          <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-ink-secondary">
            {story.summary}
          </p>
        ) : null}

        {/* Publication-level bias distribution — rendered only when the
            story has 3+ rated outlets. Shares the visual language of
            the full Story Detail bar so the two surfaces read as one
            system, but stays compact enough that it doesn't compete
            with the display headline. */}
        <div className="mt-6 max-w-2xl">
          <CompactBiasBar story={story} />
        </div>

        <div className="mt-5 flex items-center justify-between gap-4">
          <StoryMeta story={story} variant="featured" />
          <span
            className={cn(
              "hidden shrink-0 items-center gap-1.5 sm:inline-flex",
              "text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted",
              "transition-colors group-hover:text-accent",
            )}
            aria-hidden
          >
            Read comparison
            <IconArrowUpRight
              size={13}
              className="transition-transform duration-200 ease-editorial group-hover:translate-x-[1px] group-hover:-translate-y-[1px]"
            />
          </span>
        </div>
      </Link>
    </article>
  );
}
