import { Link } from "react-router-dom";

import { CompactBiasBar } from "@/components/story-detail/CompactBiasBar";
import type { StorySummary } from "@/api/types";
import { cn } from "@/lib/cn";
import { StoryMeta } from "./StoryMeta";

/**
 * Secondary story card. Sits next to <FeaturedStory /> in the Hot Now
 * grid, and can also be composed into the Discover section. Not a
 * heavy rounded box — a thin top hairline, a mid-size Fraunces
 * headline, then metadata. The card scales its typography with the
 * `size` prop so the Hot Now sidebar and the Discover grid can share
 * one component.
 */
export function StoryCard({
  story,
  size = "md",
  className,
  showTopic = true,
}: {
  story: StorySummary;
  size?: "sm" | "md" | "lg";
  className?: string;
  showTopic?: boolean;
}) {
  const headlineCls =
    size === "lg"
      ? "text-[22px] leading-[1.18] sm:text-[24px]"
      : size === "sm"
      ? "text-[15.5px] leading-snug sm:text-[16.5px]"
      : "text-[17px] leading-snug sm:text-[18.5px]";

  const summaryCls =
    size === "lg"
      ? "mt-2.5 line-clamp-3 text-[13.5px]"
      : "mt-2 line-clamp-2 text-[13px]";

  return (
    <article className={cn("group relative", className)}>
      <Link
        to={`/stories/${story.id}`}
        className={cn(
          "block h-full",
          "border-t border-ink-primary/15 pt-4",
          "transition-colors duration-150 ease-editorial",
        )}
      >
        <h3
          className={cn(
            "font-display tracking-[-0.01em] text-ink-primary",
            "transition-colors group-hover:text-accent-strong",
            headlineCls,
          )}
        >
          {story.title}
        </h3>

        {story.summary && size !== "sm" ? (
          <p className={cn("max-w-[46ch] leading-relaxed text-ink-secondary", summaryCls)}>
            {story.summary}
          </p>
        ) : null}

        <div className="mt-3">
          <StoryMeta
            story={story}
            variant={size === "sm" ? "compact" : "default"}
            showTopic={showTopic}
          />
        </div>

        {/* Publication-level bias distribution — hidden unless the
            story has 3+ rated outlets. Skipped on the ``sm`` variant
            which is too dense for a secondary strip; drops the tiny
            L/C/R legend on the ``md`` variant to keep the card tight. */}
        {size !== "sm" ? (
          <div className="mt-3">
            <CompactBiasBar story={story} showLabels={size === "lg"} />
          </div>
        ) : null}
      </Link>
    </article>
  );
}
