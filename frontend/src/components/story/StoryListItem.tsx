import { Link } from "react-router-dom";

import { IconArrowUpRight } from "@/components/ui/Icon";
import { formatCount, formatRelative } from "@/lib/format";
import type { StorySummary } from "@/api/types";
import { cn } from "@/lib/cn";

/**
 * Compact editorial list row.
 *
 * Two modes, one component:
 *   - `mode="numbered"` (default) — a "01, 02, 03" newsroom feed row.
 *     Used by the Hot Now compact tail-list and the Discover section.
 *   - `mode="time"` — a relative-time-first row. Used by Just Updated.
 *
 * The row is a link to the story detail. The right side shows the
 * outlet count as a small right-aligned data reading; on hover a
 * northeast arrow slides in as an affordance.
 */
export type StoryListItemMode = "numbered" | "time";

export function StoryListItem({
  story,
  index,
  mode = "numbered",
  className,
}: {
  story: StorySummary;
  index?: number;
  mode?: StoryListItemMode;
  className?: string;
}) {
  const outletCount = story.outlet_slugs?.length ?? 0;

  return (
    <li className={className}>
      <Link
        to={`/stories/${story.id}`}
        className={cn(
          "group grid items-baseline gap-x-4 gap-y-1.5 py-4",
          "transition-colors duration-150 ease-soft",
          "hover:bg-surface-alt/50",
          mode === "time"
            ? "grid-cols-[74px_minmax(0,1fr)_auto] sm:grid-cols-[90px_minmax(0,1fr)_auto]"
            : "grid-cols-[38px_minmax(0,1fr)_auto]",
        )}
      >
        {/* Left rail — number OR relative time */}
        {mode === "numbered" ? (
          <div className="tabular pt-0.5 text-[12.5px] font-semibold text-ink-muted transition-colors group-hover:text-accent">
            {typeof index === "number" ? index.toString().padStart(2, "0") : "—"}
          </div>
        ) : (
          <div className="tabular pt-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
            {formatRelative(story.last_seen_at)}
          </div>
        )}

        {/* Headline + secondary line */}
        <div className="min-w-0">
          <h3
            className={cn(
              "font-display text-ink-primary transition-colors group-hover:text-accent-strong",
              "text-[16px] leading-snug tracking-[-0.005em] sm:text-[17.5px]",
            )}
          >
            {story.title}
          </h3>

          {/* Secondary meta line — kept extremely compact. */}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
            <span className="tabular">
              {formatCount(story.article_count)}{" "}
              {story.article_count === 1 ? "article" : "articles"}
            </span>
            {story.topic ? (
              <>
                <span aria-hidden className="text-ink-muted/40">·</span>
                <span className="font-medium normal-case tracking-normal text-ink-secondary">
                  {story.topic}
                </span>
              </>
            ) : null}
            {mode === "numbered" ? (
              <>
                <span aria-hidden className="text-ink-muted/40">·</span>
                <span className="tabular font-medium normal-case tracking-normal">
                  {formatRelative(story.last_seen_at)}
                </span>
              </>
            ) : null}
          </div>
        </div>

        {/* Right rail — outlet-count reading + arrow */}
        <div className="flex items-baseline gap-2 pl-2 text-right">
          <div className="tabular text-[12.5px] font-semibold text-ink-primary">
            {formatCount(outletCount)}
            <span className="ml-1 text-[9.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
              {outletCount === 1 ? "outlet" : "outlets"}
            </span>
          </div>
          <IconArrowUpRight
            size={13}
            className="hidden translate-y-[1px] text-ink-muted transition-all duration-200 ease-editorial group-hover:translate-x-[1px] group-hover:-translate-y-[0px] group-hover:text-accent sm:inline-block"
          />
        </div>
      </Link>
    </li>
  );
}
