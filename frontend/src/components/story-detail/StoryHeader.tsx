import { useMemo } from "react";

import { cn } from "@/lib/cn";
import {
  formatCount,
  formatDateLong,
  formatRelative,
} from "@/lib/format";
import type { StoryDetail as StoryDetailPayload } from "@/api/types";

import { MetaCell } from "./primitives";

/**
 * FEATURE 1 — Story Header
 *
 * The editorial masthead for a story. Sets the premise: what the
 * story is about, how much coverage it has, and when it moved. Sized
 * for the front-of-page: a heavy 2px top rule as a broadsheet tell,
 * a display-scale headline in Fraunces, and a compact data strip
 * beneath.
 *
 * The header is intentionally designed to look complete WITHOUT a hero
 * image. When image support arrives in a later phase the media block
 * will slot in above the headline; nothing else in the header will
 * need to change. A single `bias` slot is reserved on the right of the
 * header for the future Media Bias Bar and rendered only when a
 * caller passes children into it (nothing does today).
 */
export function StoryHeader({
  story,
  bias,
}: {
  story: StoryDetailPayload;
  /**
   * Reserved slot for the future <MediaBiasBar />. When null the
   * space is not rendered — the header must look complete without it.
   */
  bias?: React.ReactNode;
}) {
  const dateRange = useMemo(
    () => formatDateRange(story.first_seen_at, story.last_seen_at),
    [story.first_seen_at, story.last_seen_at],
  );
  const outletCount = story.outlet_slugs?.length ?? 0;
  const spread = story.framing_spread ?? story.comparison?.framing_spread ?? null;

  return (
    <header className="reveal-up">
      {/* Masthead strip — thin caps line with the story's provenance. */}
      <div className="flex flex-wrap items-baseline justify-between gap-y-2 border-t-2 border-ink-primary pt-3 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-ink-primary">
            {story.topic ? story.topic : "Story"}
          </span>
          <span aria-hidden className="text-ink-muted/40">/</span>
          <span>
            {formatCount(outletCount)} outlet{outletCount === 1 ? "" : "s"}
          </span>
          <span aria-hidden className="text-ink-muted/40">/</span>
          <span>
            {formatCount(story.article_count)} article{story.article_count === 1 ? "" : "s"}
          </span>
        </div>
        <div className="tabular text-ink-muted">{dateRange}</div>
      </div>

      {/* Display headline. Fraunces, deep near-black on warm off-white. */}
      <h1 className="mt-6 font-display text-[36px] leading-[1.06] tracking-[-0.02em] text-ink-primary sm:mt-8 sm:text-[52px] md:text-[62px]">
        {story.title}
      </h1>

      {/* Optional slot for the (future) Media Bias Bar. Rendered on its
          own row so it doesn't compete with the headline typographically. */}
      {bias ? (
        <div className="mt-6 border-t border-ink-primary/10 pt-6">
          {bias}
        </div>
      ) : null}

      {/* Metadata data-strip. Kept beneath the headline so the eye
          reaches the story text quickly. */}
      <div
        className={cn(
          "mt-8 flex flex-wrap items-baseline gap-x-10 gap-y-4",
          "border-b border-ink-primary/10 pb-8",
        )}
      >
        <MetaCell
          label="Framing spread"
          value={formatSpread(spread)}
          tone={spreadTone(spread)}
        />
        <MetaCell
          label="Last seen"
          value={formatRelative(story.last_seen_at)}
        />
        <MetaCell
          label="First seen"
          value={formatRelative(story.first_seen_at)}
        />
        {story.comparison?.generated_at ? (
          <MetaCell
            label="Analysed"
            value={formatRelative(story.comparison.generated_at)}
          />
        ) : null}
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Small formatters kept local to the header
// ---------------------------------------------------------------------------

function formatDateRange(firstIso: string, lastIso: string): string {
  const first = new Date(firstIso);
  const last = new Date(lastIso);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime())) return "";
  const sameDay =
    first.getFullYear() === last.getFullYear() &&
    first.getMonth() === last.getMonth() &&
    first.getDate() === last.getDate();
  if (sameDay) return formatDateLong(first).toUpperCase();
  return `${formatDateLong(first)} — ${formatDateLong(last)}`.toUpperCase();
}

function formatSpread(spread: number | null | undefined): string {
  if (spread === null || spread === undefined || !Number.isFinite(spread)) {
    return "—";
  }
  return spread.toFixed(2);
}

function spreadTone(spread: number | null | undefined): string | undefined {
  if (spread === null || spread === undefined || !Number.isFinite(spread)) {
    return "text-ink-muted";
  }
  if (spread >= 0.5) return "text-framing-critical";
  if (spread >= 0.25) return "text-accent";
  return undefined;
}
