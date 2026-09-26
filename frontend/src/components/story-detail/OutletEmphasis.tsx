import { useMemo, useState } from "react";

import { cn } from "@/lib/cn";
import type {
  ArticleInStory,
  StoryComparisonPayload,
} from "@/api/types";

import {
  outletsEmphasisFromMatrix,
  type EmphasisItem,
  type OutletEmphasisRow,
} from "./helpers";
import { Chip, StorySection } from "./primitives";

/**
 * FEATURE 3 — What Each Outlet Emphasized
 *
 * Editorial visualisation of ``story_comparisons.coverage_matrix``.
 * Each outlet is a stanza in a stacked list: outlet name on the left,
 * their strongest weighted themes on the right. When theme weights are
 * present we render them as short proportional bars; when they aren't
 * we fall back to plain chip labels so older analyses still render.
 *
 * We also surface a small "Evidence from their coverage" expander
 * seeded with actual evidence snippets pulled from that outlet's
 * article analyses. Snippets are verbatim from the source — we never
 * paraphrase.
 *
 * Layout scales to many outlets because it's a straightforward
 * vertical stack; a page with 12 outlets reads as an editorial list,
 * not a wide comparison table.
 */
export function OutletEmphasis({
  comparison,
  articles,
}: {
  comparison: StoryComparisonPayload | null;
  articles: ArticleInStory[];
}) {
  const rows = useMemo(
    () =>
      outletsEmphasisFromMatrix(comparison?.coverage_matrix ?? null, articles),
    [comparison?.coverage_matrix, articles],
  );

  // Hide the whole section when the backend has produced no matrix.
  // The design brief is explicit: don't render placeholders for data
  // we don't have.
  if (rows.length === 0) return null;

  return (
    <StorySection
      eyebrow="What each outlet emphasized"
      title="Where the coverage focuses"
      lede="Themes drawn from each outlet's coverage of this story, ordered by how strongly the analysis surfaced them."
    >
      <ol className="divide-y divide-ink-primary/10 border-y border-ink-primary/10">
        {rows.map((row) => (
          <OutletEmphasisEntry key={row.slug} row={row} />
        ))}
      </ol>
    </StorySection>
  );
}

// ---------------------------------------------------------------------------
// One outlet's row
// ---------------------------------------------------------------------------

function OutletEmphasisEntry({ row }: { row: OutletEmphasisRow }) {
  const [expanded, setExpanded] = useState(false);
  const hasWeights = row.themes.some((t) => t.weight !== null);
  const evidencePreview = row.supportingEvidence.slice(0, 3);
  const evidenceCount = evidencePreview.length;

  return (
    <li className="py-6 md:py-7">
      <div className="grid grid-cols-1 gap-x-8 md:grid-cols-[minmax(0,180px)_minmax(0,1fr)]">
        {/* Left column: outlet identity */}
        <div className="mb-3 md:mb-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-primary">
            {row.name}
          </div>
          <div className="tabular mt-1 text-[11px] text-ink-muted">
            {row.themes.length} theme{row.themes.length === 1 ? "" : "s"}
          </div>
        </div>

        {/* Right column: themes */}
        <div className="min-w-0">
          {row.themes.length === 0 ? (
            <p className="text-[12.5px] text-ink-muted">
              No emphasised themes surfaced for this outlet.
            </p>
          ) : hasWeights ? (
            <ul className="space-y-2.5">
              {row.themes.map((t, i) => (
                <ThemeBar key={`${t.label}-${i}`} item={t} />
              ))}
            </ul>
          ) : (
            <div className="flex flex-wrap gap-2">
              {row.themes.map((t, i) => (
                <Chip key={`${t.label}-${i}`}>{t.label}</Chip>
              ))}
            </div>
          )}

          {evidenceCount > 0 ? (
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
                {expanded ? "Hide evidence" : `Evidence from their coverage`}
              </button>
              {expanded ? (
                <ul className="mt-3 space-y-3 border-l-2 border-accent/30 pl-4">
                  {evidencePreview.map((snippet, i) => (
                    <li
                      key={i}
                      className="font-display text-[14px] leading-[1.55] italic text-ink-secondary"
                    >
                      &ldquo;{snippet}&rdquo;
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// A single weighted theme rendered as a bar.
// ---------------------------------------------------------------------------

function ThemeBar({ item }: { item: EmphasisItem }) {
  const weight = item.weight ?? 0;
  const pct = Math.max(6, Math.min(100, Math.round(weight * 100)));

  return (
    <li className="grid grid-cols-[minmax(0,1fr)_36px] items-center gap-x-3">
      <div className="min-w-0">
        <div className="mb-1 flex items-baseline gap-3">
          <span className="truncate text-[13px] leading-tight text-ink-primary">
            {item.label}
          </span>
        </div>
        <div className="relative h-[3px] w-full overflow-hidden rounded-full bg-surface-inset">
          <span
            className="absolute inset-y-0 left-0 rounded-full bg-ink-primary/70"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <div className="tabular text-right text-[11px] font-medium text-ink-muted">
        {item.weight === null ? "—" : `${Math.round(weight * 100)}`}
      </div>
    </li>
  );
}
