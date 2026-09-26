import { useMemo } from "react";

import { cn } from "@/lib/cn";
import { formatCount, formatSignedDecimal } from "@/lib/format";
import { FRAMING_META, type FramingLabel } from "@/lib/constants";
import type {
  ArticleInStory,
  StoryDetail as StoryDetailPayload,
} from "@/api/types";

import {
  aggregateFramingByOutlet,
  bucketFor,
  type OutletFramingRow,
} from "./helpers";
import { StorySection } from "./primitives";

/**
 * FEATURE 5 — How the Story Is Framed
 *
 * Renders the mean framing score for each outlet on the -1 (critical)
 * to +1 (supportive) scale, along with confidence, a bucketed label
 * (Critical / Neutral / Supportive / Mixed / Insufficient), and the
 * story-level framing spread.
 *
 * Framing is article-level. It is NOT the same as political orientation
 * — the design brief is explicit about this. This section uses only
 * critical/neutral/supportive vocabulary, and the framing disclaimer
 * is rendered prominently at the top so a reader can never confuse
 * the two.
 */
export function FramingSection({
  story,
  articles,
}: {
  story: StoryDetailPayload;
  articles: ArticleInStory[];
}) {
  const rows = useMemo(() => aggregateFramingByOutlet(articles), [articles]);
  const spread = story.framing_spread ?? story.comparison?.framing_spread ?? null;

  // If Enrichment hasn't produced any framing scores, there's nothing
  // to visualise. We keep the disclaimer out of an otherwise-empty
  // section — the section header and the empty state alone are enough.
  const hasAnyScore = rows.some((r) => r.meanScore !== null);
  if (rows.length === 0) return null;

  return (
    <StorySection
      eyebrow="How the story is framed"
      title="Framing per outlet"
      lede={
        <>
          Mean framing score across each outlet's articles in this cluster.
          <br className="hidden sm:block" />
          <span className="tabular">−1.0 critical · 0 neutral · +1.0 supportive.</span>
        </>
      }
      aside={<SpreadPill spread={spread} />}
    >
      {hasAnyScore ? (
        <>
          <FramingLegend />
          <ul className="divide-y divide-ink-primary/10 border-y border-ink-primary/10">
            {rows.map((r) => (
              <FramingRow key={r.slug} row={r} />
            ))}
          </ul>

          {/* Framing disclaimer — kept prominent per the architecture
              requirement. Not gate-kept behind an expander. */}
          <p className="mt-6 max-w-3xl text-[11.5px] leading-relaxed text-ink-muted">
            {story.framing_disclaimer ??
              "NewsLens provides automated framing indicators based on article " +
                "content. These describe observed coverage patterns and should " +
                "not be interpreted as definitive judgments about an outlet."}
          </p>
        </>
      ) : (
        <p className="text-[13.5px] text-ink-muted">
          No framing scores have been produced for the articles in this story yet.
        </p>
      )}
    </StorySection>
  );
}

// ---------------------------------------------------------------------------
// A single outlet's row
// ---------------------------------------------------------------------------

function FramingRow({ row }: { row: OutletFramingRow }) {
  const bucket: FramingLabel | null = row.bucket;
  const bucketMeta = bucket ? FRAMING_META[bucket] : null;
  const conf = row.meanConfidence;

  return (
    <li className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 py-5 sm:gap-x-6">
      {/* Outlet identity */}
      <div className="min-w-0">
        <div className="truncate text-[12px] font-semibold uppercase tracking-[0.12em] text-ink-primary">
          {row.name}
        </div>
        <div className="tabular mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-ink-muted">
          <span>
            {formatCount(row.scoredCount)} of {formatCount(row.count)} scored
          </span>
          {conf !== null ? (
            <>
              <span aria-hidden className="text-ink-muted/40">·</span>
              <span>{Math.round(conf * 100)}% conf</span>
            </>
          ) : null}
        </div>
      </div>

      {/* Track visualisation */}
      <FramingScoreTrack row={row} />

      {/* Numeric score + bucket label */}
      <div className="text-right">
        <div className="tabular font-display text-[19px] font-semibold leading-none text-ink-primary">
          {formatSignedDecimal(row.meanScore, 2)}
        </div>
        <div
          className={cn(
            "mt-1 text-[10.5px] font-semibold uppercase tracking-[0.12em]",
            bucketMeta ? "" : "text-ink-muted",
          )}
          style={bucketMeta ? { color: bucketMeta.colorVar } : undefined}
        >
          {bucketMeta ? bucketMeta.label : "—"}
        </div>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// The -1 to +1 track. Kept purely presentational.
// ---------------------------------------------------------------------------

function FramingScoreTrack({ row }: { row: OutletFramingRow }) {
  if (row.meanScore === null || !Number.isFinite(row.meanScore)) {
    return (
      <div className="relative h-1.5 w-full rounded-full bg-surface-inset opacity-40" />
    );
  }
  const clamped = Math.max(-1, Math.min(1, row.meanScore));
  const pct = ((clamped + 1) / 2) * 100;
  const bucket = bucketFor(clamped);
  const dotClass =
    bucket === "critical"
      ? "bg-framing-critical"
      : bucket === "supportive"
      ? "bg-framing-supportive"
      : "bg-framing-neutral";

  return (
    <div className="relative h-1.5 w-full rounded-full bg-surface-inset" role="presentation">
      {/* origin marker at 50% */}
      <span
        aria-hidden
        className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-ink-primary/25"
        style={{ left: "50%" }}
      />
      {/* per-article ticks — provide a light dot-plot for outlets that
          have several articles, so a reader can see how tightly the
          scores cluster around the mean. */}
      {row.scores.length > 1
        ? row.scores.map((s, i) => {
            const cl = Math.max(-1, Math.min(1, s));
            const p = ((cl + 1) / 2) * 100;
            return (
              <span
                key={i}
                aria-hidden
                className="absolute top-1/2 h-1.5 w-px -translate-y-1/2 bg-ink-primary/20"
                style={{ left: `${p}%` }}
              />
            );
          })
        : null}
      {/* mean dot */}
      <span
        aria-hidden
        className={cn(
          "absolute top-1/2 h-3 w-3 -translate-y-1/2 -translate-x-1/2 rounded-full border-2 border-canvas",
          dotClass,
        )}
        style={{
          left: `${pct}%`,
          transition: "left 320ms cubic-bezier(0.22, 0.61, 0.36, 1)",
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Legend row
// ---------------------------------------------------------------------------

function FramingLegend() {
  const entries: Array<{ key: FramingLabel; hint: string }> = [
    { key: "critical", hint: "≤ −0.15" },
    { key: "neutral", hint: "−0.15 – +0.15" },
    { key: "supportive", hint: "≥ +0.15" },
  ];
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-[11px] font-medium text-ink-muted">
      {entries.map(({ key, hint }) => {
        const meta = FRAMING_META[key];
        return (
          <div key={key} className="flex items-center gap-2">
            <span
              aria-hidden
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: meta.colorVar }}
            />
            <span className="text-ink-primary">{meta.label}</span>
            <span className="tabular text-ink-muted/80">{hint}</span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Spread pill — the story-level framing spread as a tone-tinted chip.
// ---------------------------------------------------------------------------

function SpreadPill({ spread }: { spread: number | null }) {
  if (spread === null || !Number.isFinite(spread)) return null;
  const level =
    spread >= 0.5 ? "high" : spread >= 0.25 ? "moderate" : "narrow";

  const tone =
    level === "high"
      ? "bg-framing-critical-tint text-framing-critical border-framing-critical/25"
      : level === "moderate"
      ? "bg-accent-soft text-accent-ink border-accent/25"
      : "bg-surface-alt text-ink-secondary border-subtle";

  return (
    <div className={cn("inline-flex flex-col items-start rounded-md border px-3 py-2", tone)}>
      <span className="text-[10px] font-semibold uppercase tracking-[0.14em]">
        Framing spread
      </span>
      <span className="tabular mt-0.5 font-display text-[17px] font-semibold leading-none">
        {spread.toFixed(2)}
      </span>
      <span className="mt-1 text-[10.5px] font-medium">
        {level === "high"
          ? "Wide divergence"
          : level === "moderate"
          ? "Some divergence"
          : "Narrow divergence"}
      </span>
    </div>
  );
}
