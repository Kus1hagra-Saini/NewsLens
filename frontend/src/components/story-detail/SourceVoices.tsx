import { useMemo, useState } from "react";

import { cn } from "@/lib/cn";
import { formatCount } from "@/lib/format";
import type { ArticleInStory } from "@/api/types";

import {
  aggregateSourceDistribution,
  collectQuotedSources,
  totalsBycategoryAcrossOutlets,
  SOURCE_CATEGORIES,
  SOURCE_CATEGORY_LABELS,
  type CleanQuotedSource,
  type OutletSourceBreakdown,
  type SourceCategory,
} from "./helpers";
import { Chip, StorySection } from "./primitives";

/**
 * FEATURE 6 — Who Is Being Heard?
 *
 * Combines source_distribution (counts by category per outlet) and
 * quoted_sources (attributed quotes with stance) into a single
 * editorial section that answers "which kinds of voices are showing
 * up in this coverage, and who are they?".
 *
 * Two subsections:
 *
 *   - <SourceTypeBreakdown /> — a story-wide totals bar plus a
 *     per-outlet stacked mix so a reader can see who each outlet
 *     leans on.
 *   - <SourceVoices /> — a small selection of representative quoted
 *     speakers, verbatim (never paraphrased), attributed to their
 *     outlet.
 *
 * Language is deliberately hedged: "Sources identified in analyzed
 * coverage" and "Voices identified" — not "everyone quoted" or "all
 * the sources", because source extraction is LLM-derived and cannot
 * be treated as ground truth.
 */
export function SourceVoicesSection({
  articles,
}: {
  articles: ArticleInStory[];
}) {
  const outletBreakdowns = useMemo(
    () => aggregateSourceDistribution(articles),
    [articles],
  );
  const storyTotals = useMemo(
    () => totalsBycategoryAcrossOutlets(outletBreakdowns),
    [outletBreakdowns],
  );
  const grandTotal = useMemo(
    () => Object.values(storyTotals).reduce((s, v) => s + v, 0),
    [storyTotals],
  );

  const quotes = useMemo(() => collectQuotedSources(articles), [articles]);

  // Nothing to show: hide the whole section rather than an empty tile.
  if (grandTotal === 0 && quotes.length === 0) return null;

  return (
    <StorySection
      eyebrow="Who is being heard?"
      title="Voices in the coverage"
      lede="A rough map of who this story's coverage relies on — the categories of sources cited and, where present, representative quoted speakers."
    >
      {grandTotal > 0 ? (
        <SourceTypeBreakdown
          storyTotals={storyTotals}
          grandTotal={grandTotal}
          outletBreakdowns={outletBreakdowns}
        />
      ) : null}

      {quotes.length > 0 ? (
        <div className={cn(grandTotal > 0 ? "mt-12" : "")}>
          <SourceVoices quotes={quotes} />
        </div>
      ) : null}

      <p className="mt-6 text-[11px] uppercase tracking-[0.14em] text-ink-muted">
        Sources identified in analyzed coverage. NewsLens does not claim
        exhaustive attribution.
      </p>
    </StorySection>
  );
}

// ---------------------------------------------------------------------------
// SourceTypeBreakdown — the counts visualisation
// ---------------------------------------------------------------------------

function SourceTypeBreakdown({
  storyTotals,
  grandTotal,
  outletBreakdowns,
}: {
  storyTotals: Record<SourceCategory, number>;
  grandTotal: number;
  outletBreakdowns: OutletSourceBreakdown[];
}) {
  // Sort categories by total count DESC for the story-wide list; the
  // per-outlet stacked bar keeps the same order so the reader can hop
  // between the two views without re-orienting.
  const orderedCategories = useMemo(() => {
    return [...SOURCE_CATEGORIES].sort(
      (a, b) => storyTotals[b] - storyTotals[a],
    );
  }, [storyTotals]);

  return (
    <div>
      <h3 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-primary">
        Across all coverage in this story
      </h3>
      <ul className="mt-3 space-y-2">
        {orderedCategories.map((cat) => {
          const count = storyTotals[cat];
          const pct = grandTotal > 0 ? (count / grandTotal) * 100 : 0;
          return (
            <li key={cat} className="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)_auto] items-center gap-x-3 sm:gap-x-5">
              <div className="truncate text-[13px] text-ink-primary">
                {SOURCE_CATEGORY_LABELS[cat]}
              </div>
              <div className="relative h-[6px] w-full overflow-hidden rounded-full bg-surface-inset">
                <span
                  className={cn(
                    "absolute inset-y-0 left-0 rounded-full",
                    CATEGORY_BAR_CLASS[cat],
                  )}
                  style={{ width: `${Math.max(2, pct)}%` }}
                />
              </div>
              <div className="tabular w-14 text-right text-[12px] font-medium text-ink-secondary">
                {formatCount(count)}
                <span className="ml-1 text-ink-muted">
                  ({pct.toFixed(0)}%)
                </span>
              </div>
            </li>
          );
        })}
      </ul>

      {/* Per-outlet stacked breakdown */}
      {outletBreakdowns.length > 0 ? (
        <div className="mt-10">
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-primary">
            How each outlet's mix compares
          </h3>
          <ul className="mt-4 divide-y divide-ink-primary/10 border-y border-ink-primary/10">
            {outletBreakdowns.map((row) => (
              <OutletMixRow key={row.slug} row={row} order={orderedCategories} />
            ))}
          </ul>
          {/* Category legend for the stacked bars */}
          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-[11px] text-ink-muted">
            {orderedCategories.map((cat) => (
              <div key={cat} className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className={cn(
                    "inline-block h-2 w-2 rounded-sm",
                    CATEGORY_BAR_CLASS[cat],
                  )}
                />
                <span>{SOURCE_CATEGORY_LABELS[cat]}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function OutletMixRow({
  row,
  order,
}: {
  row: OutletSourceBreakdown;
  order: SourceCategory[];
}) {
  const total = row.total;
  return (
    <li className="grid grid-cols-[minmax(0,160px)_minmax(0,1fr)_auto] items-center gap-x-4 py-3">
      <div className="min-w-0 truncate text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-primary">
        {row.name}
      </div>
      <div className="relative flex h-[10px] w-full overflow-hidden rounded-full bg-surface-inset">
        {total === 0 ? null : (
          order.map((cat) => {
            const c = row.totals[cat];
            if (c === 0) return null;
            const pct = (c / total) * 100;
            return (
              <span
                key={cat}
                title={`${SOURCE_CATEGORY_LABELS[cat]} · ${formatCount(c)}`}
                className={cn("h-full", CATEGORY_BAR_CLASS[cat])}
                style={{ width: `${pct}%` }}
              />
            );
          })
        )}
      </div>
      <div className="tabular w-16 text-right text-[11.5px] font-medium text-ink-secondary">
        {formatCount(total)}
        <span className="ml-1 text-[10.5px] text-ink-muted">src</span>
      </div>
    </li>
  );
}

// Distinct tones for the seven categories. Uses tokens already in the
// palette so light/dark mode both remain legible. No new hex values.
const CATEGORY_BAR_CLASS: Record<SourceCategory, string> = {
  government: "bg-ink-primary/80",
  opposition: "bg-accent/80",
  expert: "bg-framing-supportive/80",
  civil_society: "bg-framing-critical/80",
  corporate: "bg-ink-secondary/70",
  unnamed_source: "bg-ink-muted/70",
  other: "bg-strong/70",
};

// ---------------------------------------------------------------------------
// SourceVoices — representative quotes
// ---------------------------------------------------------------------------

function SourceVoices({ quotes }: { quotes: CleanQuotedSource[] }) {
  const [showAll, setShowAll] = useState(false);
  const preview = quotes.slice(0, 6);
  const shown = showAll ? quotes : preview;
  const hiddenCount = Math.max(0, quotes.length - preview.length);

  return (
    <div>
      <h3 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-primary">
        Voices identified
      </h3>
      <ul className="mt-4 grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-2">
        {shown.map((q, i) => (
          <QuoteCard key={`${q.speaker}-${i}`} quote={q} />
        ))}
      </ul>

      {hiddenCount > 0 ? (
        <div className="mt-6">
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-sm text-[11.5px] font-semibold uppercase tracking-[0.12em] text-ink-muted transition-colors hover:text-accent"
          >
            {showAll
              ? "Show fewer voices"
              : `Show ${hiddenCount} more voice${hiddenCount === 1 ? "" : "s"}`}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function QuoteCard({ quote }: { quote: CleanQuotedSource }) {
  const stanceMeta = STANCE_META[quote.stance];
  const affiliationDisplay = quote.affiliation && quote.affiliation.trim().length > 0
    ? quote.affiliation
    : null;

  return (
    <li className="border-l-2 border-accent/30 pl-4">
      <p className="font-display text-[16px] leading-[1.55] italic text-ink-primary sm:text-[17px]">
        &ldquo;{quote.quote}&rdquo;
      </p>
      <div className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[12px] text-ink-secondary">
        <span className="font-semibold text-ink-primary">— {quote.speaker}</span>
        {affiliationDisplay ? (
          <>
            <span aria-hidden className="text-ink-muted/40">·</span>
            <span className="text-ink-secondary">{affiliationDisplay}</span>
          </>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
        <span className="uppercase tracking-[0.12em]">In {quote.outletName}</span>
        {stanceMeta ? (
          <>
            <span aria-hidden className="text-ink-muted/40">·</span>
            <Chip tone={stanceMeta.tone} className="py-[2px] text-[10.5px]">
              {stanceMeta.label}
            </Chip>
          </>
        ) : null}
      </div>
    </li>
  );
}

const STANCE_META: Record<
  CleanQuotedSource["stance"],
  { label: string; tone: "default" | "muted" | "accent" } | null
> = {
  supports: { label: "Supportive stance", tone: "accent" },
  criticizes: { label: "Critical stance", tone: "default" },
  neutral: { label: "Neutral stance", tone: "muted" },
  unclear: { label: "Stance unclear", tone: "muted" },
  unknown: null,
};
