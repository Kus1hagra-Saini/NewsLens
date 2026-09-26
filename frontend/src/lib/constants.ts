/**
 * NewsLens framing disclaimer — the exact wording from architecture §5.
 * Kept as a single constant so every surface renders it identically.
 */
export const FRAMING_DISCLAIMER =
  "NewsLens provides automated framing indicators based on article content. " +
  "These describe observed coverage patterns and should not be interpreted " +
  "as definitive judgments about an outlet.";

export const BRAND_NAME = "NewsLens";

/**
 * Product tagline — a short editorial promise, set below the
 * wordmark on desktop and inside the mobile navigation sheet footer.
 * "News intelligence" was the old SaaS-y phrasing; the redesign
 * frames the product around the reader's actual question.
 */
export const BRAND_TAGLINE = "See how the news is being covered.";

export type FramingLabel =
  | "critical"
  | "neutral"
  | "supportive"
  | "mixed"
  | "insufficient"
  | "unlabeled";

export interface FramingLabelMeta {
  label: string;
  colorVar: string;        // maps to a CSS variable via Tailwind
  swatchClass: string;
  chipClass: string;
  /** Very short helper text — used in legend and tooltip. */
  helper: string;
}

/**
 * Framing label metadata. Non-political vocabulary throughout. Colors
 * are burnt-orange (critical) / warm slate (neutral) / deep teal
 * (supportive) — chosen for good AA contrast on both themes AND to
 * stay visually distinct from the coral-red brand accent.
 */
export const FRAMING_META: Record<FramingLabel, FramingLabelMeta> = {
  critical: {
    label: "Critical",
    colorVar: "rgb(var(--color-framing-critical))",
    swatchClass: "bg-framing-critical",
    chipClass:
      "bg-framing-critical-tint text-framing-critical border border-framing-critical/25",
    helper: "Framing challenges the primary subject",
  },
  neutral: {
    label: "Neutral",
    colorVar: "rgb(var(--color-framing-neutral))",
    swatchClass: "bg-framing-neutral",
    chipClass:
      "bg-framing-neutral-tint text-framing-neutral border border-framing-neutral/25",
    helper: "Framing is descriptive or balanced",
  },
  supportive: {
    label: "Supportive",
    colorVar: "rgb(var(--color-framing-supportive))",
    swatchClass: "bg-framing-supportive",
    chipClass:
      "bg-framing-supportive-tint text-framing-supportive border border-framing-supportive/25",
    helper: "Framing endorses the primary subject",
  },
  mixed: {
    label: "Mixed",
    colorVar: "rgb(var(--color-ink-secondary))",
    swatchClass: "bg-ink-secondary",
    chipClass: "bg-surface-alt text-ink-secondary border border-subtle",
    helper: "Both critical and supportive signals",
  },
  insufficient: {
    label: "Insufficient",
    colorVar: "rgb(var(--color-ink-muted))",
    swatchClass: "bg-ink-muted",
    chipClass: "bg-surface-alt text-ink-muted border border-subtle",
    helper: "Not enough signal to label",
  },
  unlabeled: {
    label: "Unlabeled",
    colorVar: "rgb(var(--color-ink-muted))",
    swatchClass: "bg-ink-muted",
    chipClass: "bg-surface-alt text-ink-muted border border-subtle",
    helper: "Analysis has not run yet",
  },
};
