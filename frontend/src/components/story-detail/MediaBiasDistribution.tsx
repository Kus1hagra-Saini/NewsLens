import { useState } from "react";

import { cn } from "@/lib/cn";
import type {
  BiasCategory,
  BiasDistribution,
  BiasDistributionSource,
} from "@/api/types";

import {
  BIAS_CATEGORY_LABEL,
  BIAS_CATEGORY_SWATCH_CLASS,
  BiasBar,
} from "./BiasBar";
import { Chip, StorySection } from "./primitives";

/**
 * FEATURE — Media Bias Distribution
 *
 * A compact editorial bar showing how the outlets COVERING this story
 * distribute across three broad buckets on a publication-level bias
 * axis: Left / Center / Right.
 *
 * Critical rules baked into this component:
 *
 *   - The distribution describes RATED PUBLICATIONS covering the story,
 *     never the story itself and never any individual article.
 *   - The buckets come from documented THIRD-PARTY sources (currently
 *     MBFC). NewsLens does not generate the ratings.
 *   - Unrated outlets are named as unrated and never silently placed
 *     in a bucket.
 *   - The original external label is preserved in the source-details
 *     expander so a reader can see the raw claim.
 *
 * The bar hides itself entirely when the backend reports ``eligible ==
 * false`` — see the two documented reasons handled below.
 */
export function MediaBiasDistribution({
  distribution,
}: {
  distribution: BiasDistribution | null;
}) {
  const [expanded, setExpanded] = useState(false);

  // Nothing to render when the backend didn't attach any payload.
  if (!distribution) return null;

  // Ineligible → show a small explanatory row rather than a fake bar.
  if (!distribution.eligible) {
    return (
      <IneligibleNote distribution={distribution} />
    );
  }

  const { counts, sources, rated_outlet_count, total_outlet_count } = distribution;
  const dist = distribution.distribution;

  return (
    <StorySection
      eyebrow="Media bias distribution"
      title="Publications covering this story"
      lede="Where the outlets covering this story sit on a publication-level bias axis, based on external ratings. Not an assessment of the story or any single article."
    >
      <BiasBarWithLegend dist={dist} counts={counts} />

      <p className="mt-4 max-w-3xl text-[12.5px] leading-relaxed text-ink-secondary">
        Based on <span className="tabular font-semibold text-ink-primary">
          {rated_outlet_count}
        </span>{" "}
        of <span className="tabular font-semibold text-ink-primary">
          {total_outlet_count}
        </span>{" "}
        outlet{total_outlet_count === 1 ? "" : "s"} covering this story.{" "}
        {distribution.unrated_outlet_count > 0 ? (
          <span className="text-ink-muted">
            {distribution.unrated_outlet_count} outlet
            {distribution.unrated_outlet_count === 1 ? "" : "s"} unrated
            in our current sources.
          </span>
        ) : null}
      </p>

      <p className="mt-3 max-w-3xl text-[11.5px] leading-relaxed text-ink-muted">
        Distribution reflects publication-level ratings of outlets covering
        this story; it does not assess the political bias of individual
        articles.
      </p>

      <div className="mt-4">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="group inline-flex items-center gap-1.5 rounded-sm text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted transition-colors hover:text-accent"
        >
          <span
            aria-hidden
            className={cn(
              "inline-block h-1 w-1 rounded-full transition-colors",
              expanded ? "bg-accent" : "bg-ink-muted/60",
            )}
          />
          {expanded ? "Hide source details" : "Show source details"}
        </button>

        {expanded ? (
          <div className="mt-4">
            <SourceDetailsTable sources={sources} />
          </div>
        ) : null}
      </div>
    </StorySection>
  );
}

// ---------------------------------------------------------------------------
// Full-size bar with legend — Story Detail treatment.
//
// The bar itself is the shared <BiasBar />; the legend row (per-
// category label + percentage + outlet count) is Story-Detail-specific
// and lives here so the compact home-page version stays lean.
// ---------------------------------------------------------------------------

function BiasBarWithLegend({
  dist,
  counts,
}: {
  dist: Record<BiasCategory, number>;
  counts: Record<BiasCategory, number>;
}) {
  const order: BiasCategory[] = ["left", "center", "right"];

  return (
    <div>
      <BiasBar distribution={dist} counts={counts} size="full" />

      {/* Legend row with labels + percentages + counts */}
      <ul className="mt-3 grid grid-cols-3 gap-3">
        {order.map((cat) => (
          <li key={cat} className="min-w-0">
            <div className="flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
              <span
                aria-hidden
                className={cn("inline-block h-2 w-2 rounded-sm", BIAS_CATEGORY_SWATCH_CLASS[cat])}
              />
              {BIAS_CATEGORY_LABEL[cat]}
            </div>
            <div className="tabular mt-0.5 font-display text-[19px] font-semibold leading-none text-ink-primary">
              {dist[cat].toFixed(dist[cat] % 1 === 0 ? 0 : 1)}%
            </div>
            <div className="tabular mt-1 text-[11px] text-ink-muted">
              {counts[cat]} outlet{counts[cat] === 1 ? "" : "s"}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Source details table — expandable
// ---------------------------------------------------------------------------

function SourceDetailsTable({
  sources,
}: {
  sources: BiasDistributionSource[];
}) {
  if (sources.length === 0) return null;

  return (
    <div>
      <div className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
        Outlet · Published rating · Category · Source
      </div>
      <ul className="divide-y divide-ink-primary/10 border-y border-ink-primary/10">
        {sources.map((s) => (
          <li
            key={`${s.outlet_slug}-${s.rating_source}`}
            className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)_minmax(0,90px)_minmax(0,120px)] items-baseline gap-x-4 py-3 text-[13px]"
          >
            <div className="min-w-0 truncate font-semibold text-ink-primary">
              {s.outlet_name}
            </div>
            <div className="min-w-0 truncate text-ink-secondary">
              {s.original_rating}
            </div>
            <div>
              <Chip
                tone={s.normalized_category === "center" ? "muted" : "default"}
                className="uppercase tracking-[0.1em] text-[10.5px]"
              >
                {BIAS_CATEGORY_LABEL[s.normalized_category]}
              </Chip>
            </div>
            <div className="tabular text-[11.5px] text-ink-muted">
              <a
                href={s.rating_url}
                target="_blank"
                rel="noopener noreferrer"
                className="border-b border-transparent transition-colors hover:border-accent hover:text-accent"
                title={s.rating_url}
              >
                {s.rating_source}
              </a>
              {s.rated_at ? (
                <>
                  {" · "}
                  <span title={`Last updated ${s.rated_at}`}>
                    {formatRatedDate(s.rated_at)}
                  </span>
                </>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 max-w-3xl text-[11px] leading-relaxed text-ink-muted">
        Ratings above are the exact published labels from each external
        source. NewsLens preserves them verbatim and does not average
        methodologies.
      </p>
    </div>
  );
}

function formatRatedDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

// ---------------------------------------------------------------------------
// Ineligible state — the bar cannot be shown for this story
// ---------------------------------------------------------------------------

function IneligibleNote({ distribution }: { distribution: BiasDistribution }) {
  const { reason, total_outlet_count, rated_outlet_count } = distribution;

  const message =
    reason === "too_few_outlets"
      ? `This story has coverage from ${total_outlet_count} outlet${
          total_outlet_count === 1 ? "" : "s"
        }. A publication-level distribution needs at least 3.`
      : `Only ${rated_outlet_count} of ${total_outlet_count} outlets covering this story have a documented rating in our current sources. A distribution needs at least 3 rated outlets.`;

  return (
    <StorySection
      eyebrow="Media bias distribution"
      title="Not enough rated coverage to show a distribution"
      lede={message}
    >
      <p className="max-w-3xl text-[11.5px] leading-relaxed text-ink-muted">
        The distribution would describe publication-level bias ratings of
        the outlets covering this story, from external documented sources.
        It never assesses the political bias of any single article.
      </p>
    </StorySection>
  );
}
