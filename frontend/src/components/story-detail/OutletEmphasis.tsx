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
 * their top-ranked themes on the right as compact pills. The backend
 * matrix frequently includes zero-weighted themes as a shape artefact
 * (every outlet grades every theme the comparison enumerated, even
 * ones they didn't actually cover); we drop those at the presentation
 * layer and cap each outlet at the top 5 remaining themes so this
 * section reads as a scannable comparison rather than a raw analytics
 * dump. The backend-ranked order from ``outletsEmphasisFromMatrix``
 * (weight DESC, then stable alpha) is preserved.
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

/** Max themes rendered per outlet in this section. See module docstring. */
const MAX_THEMES_PER_OUTLET = 5;

/**
 * Presentation-layer filter: drop zero-weight themes, cap at
 * MAX_THEMES_PER_OUTLET, keep the backend ranking. ``weight === null``
 * means the matrix cell was a plain string list (legacy shape without
 * weights) — we keep those entries because there's no weight to
 * discriminate against.
 */
function visibleThemes(themes: EmphasisItem[]): EmphasisItem[] {
  return themes
    .filter((t) => t.weight === null || t.weight > 0)
    .slice(0, MAX_THEMES_PER_OUTLET);
}

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
  const visible = useMemo(() => visibleThemes(row.themes), [row.themes]);
  const evidencePreview = row.supportingEvidence.slice(0, 3);
  const evidenceCount = evidencePreview.length;

  // Skip the whole outlet row when there is nothing meaningful to
  // show in this section — avoids leaving a "huge empty block" for
  // outlets whose matrix cell was all zeros AND whose articles
  // produced no evidence snippets.
  if (visible.length === 0 && evidenceCount === 0) return null;

  return (
    <li className="py-6 md:py-7">
      <div className="grid grid-cols-1 gap-x-8 md:grid-cols-[minmax(0,180px)_minmax(0,1fr)]">
        {/* Left column: outlet identity (theme-count line intentionally
            removed — the number is a shape artefact of the backend
            matrix, not a reader-useful signal). */}
        <div className="mb-3 md:mb-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-primary">
            {row.name}
          </div>
        </div>

        {/* Right column: top themes as compact pills, wrapping
            naturally on narrower viewports. Uses the shared ``Chip``
            primitive so this section stays visually consistent with
            the rest of the Story Detail design system. */}
        <div className="min-w-0">
          {visible.length === 0 ? (
            <p className="text-[12.5px] text-ink-muted">
              No emphasised themes surfaced for this outlet.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {visible.map((t, i) => (
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
