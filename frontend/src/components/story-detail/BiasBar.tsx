import { cn } from "@/lib/cn";
import type { BiasCategory } from "@/api/types";

/**
 * Shared segmented Left/Center/Right bar used by both the compact
 * home-page indicator and the full Story Detail visualisation.
 *
 * Only visual primitive — no eligibility logic and no data fetching.
 * Callers are responsible for handing in a distribution they've
 * already confirmed is eligible; a fully-zero distribution renders as
 * an empty track (defensive; shouldn't occur in the intended flow).
 *
 * Colours are drawn from existing palette tokens so light + dark mode
 * both work without new CSS. Kept deliberately distinct from the
 * framing tones (critical / neutral / supportive) — a reader should
 * never confuse publication-level bias with article-level framing.
 */

export const BIAS_CATEGORY_LABEL: Record<BiasCategory, string> = {
  left: "Left",
  center: "Center",
  right: "Right",
};

/** Bar-segment colours. Solid, saturation-matched across categories. */
export const BIAS_CATEGORY_BAR_CLASS: Record<BiasCategory, string> = {
  left: "bg-framing-supportive/80",
  center: "bg-ink-muted/60",
  right: "bg-accent/80",
};

/** Small swatch colours (used in legends, chips). Match the bar. */
export const BIAS_CATEGORY_SWATCH_CLASS: Record<BiasCategory, string> = {
  left: "bg-framing-supportive",
  center: "bg-ink-muted",
  right: "bg-accent",
};

const CATEGORY_ORDER: BiasCategory[] = ["left", "center", "right"];

export interface BiasBarProps {
  distribution: Record<BiasCategory, number>;
  counts: Record<BiasCategory, number>;
  /**
   * "full"    — 12px tall, used inside the Story Detail section
   * "compact" — 6px tall, used inline on story cards / featured hero
   */
  size?: "full" | "compact";
  /** Extra className for the outer container. */
  className?: string;
}

/**
 * The segmented bar itself. Segments are ordered left → center →
 * right regardless of magnitude, so the visual reading is always
 * "which side does this coverage lean?" not "which side is largest?".
 */
export function BiasBar({
  distribution,
  counts,
  size = "full",
  className,
}: BiasBarProps) {
  const heightCls = size === "compact" ? "h-1.5" : "h-3";
  return (
    <div
      className={cn(
        "flex w-full overflow-hidden rounded-full bg-surface-inset",
        heightCls,
        className,
      )}
      role="img"
      aria-label={buildAriaLabel(distribution, counts)}
    >
      {CATEGORY_ORDER.map((cat) => {
        const pct = Math.max(0, Math.min(100, distribution[cat]));
        if (pct <= 0) return null;
        return (
          <span
            key={cat}
            className={cn("h-full", BIAS_CATEGORY_BAR_CLASS[cat])}
            style={{ width: `${pct}%` }}
            title={`${BIAS_CATEGORY_LABEL[cat]}: ${counts[cat]} outlet${
              counts[cat] === 1 ? "" : "s"
            } (${pct.toFixed(1)}%)`}
          />
        );
      })}
    </div>
  );
}

function buildAriaLabel(
  distribution: Record<BiasCategory, number>,
  counts: Record<BiasCategory, number>,
): string {
  const parts = CATEGORY_ORDER.filter((c) => counts[c] > 0).map(
    (c) =>
      `${BIAS_CATEGORY_LABEL[c]} ${distribution[c].toFixed(0)}% (${counts[c]} outlet${
        counts[c] === 1 ? "" : "s"
      })`,
  );
  return `Publication bias distribution: ${parts.join(", ")}`;
}
