import { formatCount, formatRelative } from "@/lib/format";
import type { StorySummary } from "@/api/types";
import { cn } from "@/lib/cn";

/**
 * Small-caps editorial metadata line shared by every story presentation
 * component. Deliberately not a pill/badge/chip strip — it reads as a
 * dateline: OUTLET COUNT · ARTICLES · TIME · TOPIC.
 *
 * The outlet count is the most product-important number here (broad
 * coverage across outlets is what NewsLens surfaces) so it leads the
 * line and is set in the primary ink weight.
 *
 * Variants:
 *   - "default" — the full line with all four segments
 *   - "compact" — smaller type, drops the topic when space is tight
 *   - "featured" — larger, brighter, with a small solid dot before the
 *     outlet count (feels like the front-page dateline)
 */
export type StoryMetaVariant = "default" | "compact" | "featured";

export function StoryMeta({
  story,
  variant = "default",
  className,
  showTopic = true,
}: {
  story: StorySummary;
  variant?: StoryMetaVariant;
  className?: string;
  showTopic?: boolean;
}) {
  const outletCount = story.outlet_slugs?.length ?? 0;
  const articleCount = story.article_count;

  const base =
    variant === "featured"
      ? "text-[11.5px] tracking-[0.18em]"
      : variant === "compact"
      ? "text-[10.5px] tracking-[0.14em]"
      : "text-[11px] tracking-[0.16em]";

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-2.5 gap-y-1",
        "font-semibold uppercase text-ink-muted",
        base,
        className,
      )}
    >
      {variant === "featured" ? (
        <span
          aria-hidden
          className="inline-block h-[6px] w-[6px] shrink-0 rounded-full bg-accent"
        />
      ) : null}

      {/* Outlet count — the product-central number. */}
      <span className="text-ink-primary tabular">
        {formatCount(outletCount)}{" "}
        {outletCount === 1 ? "outlet" : "outlets"}
      </span>

      <span aria-hidden className="text-ink-muted/40">
        ·
      </span>

      <span className="tabular">
        {formatCount(articleCount)}{" "}
        {articleCount === 1 ? "article" : "articles"}
      </span>

      <span aria-hidden className="text-ink-muted/40">
        ·
      </span>

      <span className="tabular font-medium normal-case tracking-normal">
        {formatRelative(story.last_seen_at)}
      </span>

      {showTopic && story.topic ? (
        <>
          <span aria-hidden className="text-ink-muted/40">
            ·
          </span>
          <span className="font-medium normal-case tracking-normal text-ink-secondary">
            {story.topic}
          </span>
        </>
      ) : null}
    </div>
  );
}
