import { useStoryDetail } from "@/api/queries";
import { cn } from "@/lib/cn";
import type {
  BiasCategory,
  BiasDistribution,
  StorySummary,
} from "@/api/types";

import {
  BIAS_CATEGORY_LABEL,
  BIAS_CATEGORY_SWATCH_CLASS,
  BiasBar,
} from "./BiasBar";

/**
 * Compact publication-level bias indicator for the Home surfaces.
 *
 * Design contract:
 *   - Reuses the SAME shared <BiasBar /> primitive as the Story Detail
 *     visualisation, so both surfaces read as one system.
 *   - Reuses the SAME backend data and eligibility rules — this
 *     component NEVER classifies ratings on the frontend. It lazily
 *     fetches ``useStoryDetail(id)``, reads the backend's
 *     ``bias_distribution`` payload, and defers to the eligibility
 *     verdict there.
 *   - Renders NOTHING when the story is ineligible, when the fetch is
 *     still in flight, or when the payload's ``bias_distribution`` is
 *     absent. No skeleton flash on a home card.
 *   - Only fires the fetch when the story has 3+ outlets on its list
 *     summary. This is a cheap pre-gate that mirrors the backend's
 *     first eligibility rule and stops a Home render firing detail
 *     requests for tiny 1-outlet stories.
 *
 * The component receives a whole ``StorySummary`` (the shape the Home
 * list already has) and does the fetching itself, so callers just
 * drop it in place — no plumbing.
 */
export function CompactBiasBar({
  story,
  className,
  showLabels = true,
}: {
  story: StorySummary;
  className?: string;
  /**
   * When true (default), a tiny Left/Center/Right label + % row sits
   * under the bar. When false, only the bar is drawn (useful when
   * the caller already has a dense meta row above it).
   */
  showLabels?: boolean;
}) {
  const distribution = useCompactBiasDistribution(story);

  if (!distribution) return null;

  return (
    <div className={cn("min-w-0", className)}>
      <BiasBar
        distribution={distribution.distribution as Record<BiasCategory, number>}
        counts={distribution.counts as Record<BiasCategory, number>}
        size="compact"
      />
      {showLabels ? <CompactLegend distribution={distribution} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data hook — the gate + the (cached) fetch
// ---------------------------------------------------------------------------

/**
 * Returns the story's bias distribution when it is eligible AND
 * loaded; ``null`` otherwise. Pre-gates on ``outlet_slugs.length`` so
 * ineligible-looking stories never fire a detail request.
 *
 * The fetch reuses TanStack Query's ``useStoryDetail(id)`` cache, so
 * a subsequent navigation to /stories/{id} is already warm.
 */
function useCompactBiasDistribution(
  story: StorySummary,
): BiasDistribution | null {
  const outletCount = story.outlet_slugs?.length ?? 0;
  const preEligible = outletCount >= 3;

  // useStoryDetail respects `enabled: false` when id is null, so
  // passing null skips the fetch entirely.
  const q = useStoryDetail(preEligible ? story.id : null);
  const bd = q.data?.bias_distribution ?? null;
  if (!bd || !bd.eligible) return null;
  return bd;
}

// ---------------------------------------------------------------------------
// Tiny under-bar legend — one row, small caps
// ---------------------------------------------------------------------------

function CompactLegend({ distribution }: { distribution: BiasDistribution }) {
  const order: BiasCategory[] = ["left", "center", "right"];
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] font-medium uppercase tracking-[0.12em] text-ink-muted">
      {order.map((cat) => (
        <span key={cat} className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className={cn(
              "inline-block h-1.5 w-1.5 rounded-sm",
              BIAS_CATEGORY_SWATCH_CLASS[cat],
            )}
          />
          <span className="text-ink-secondary">{BIAS_CATEGORY_LABEL[cat]}</span>
          <span className="tabular text-ink-primary">
            {distribution.distribution[cat].toFixed(0)}%
          </span>
        </span>
      ))}
      <span aria-hidden className="text-ink-muted/40">·</span>
      <span className="tabular text-ink-muted">
        {distribution.rated_outlet_count} rated
      </span>
    </div>
  );
}
