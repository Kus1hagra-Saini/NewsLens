import { useMemo } from "react";

import { SectionHeader } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { formatCount, formatPct } from "@/lib/format";
import { FRAMING_META, type FramingLabel } from "@/lib/constants";
import { useTrends } from "@/api/queries";
import { cn } from "@/lib/cn";

// Stable, non-political display order.
const PRIMARY: FramingLabel[] = ["critical", "neutral", "supportive"];
const SECONDARY: FramingLabel[] = ["mixed", "insufficient", "unlabeled"];

interface Bucket {
  key: FramingLabel;
  count: number;
}

/**
 * Framing distribution as an editorial horizontal proportional bar —
 * a single stacked strip with three (or more) segments, primary
 * categories only (Critical / Neutral / Supportive) with a smaller
 * inline breakdown of secondary buckets below.
 *
 * Deliberately not a donut and not a political spectrum. Labels sit
 * *above* their share, in the same order every render, so the shape of
 * coverage is legible at a glance without any political vocabulary.
 */
export function FramingDonut({ windowDays = 7 }: { windowDays?: number }) {
  const query = useTrends(windowDays);

  const { primary, secondary, total } = useMemo(
    () => partition(query.data?.framing_distribution ?? []),
    [query.data],
  );
  const primaryTotal = primary.reduce((s, b) => s + b.count, 0);

  return (
    <section className="reveal-up reveal-d3">
      <SectionHeader
        kicker="Framing distribution"
        title="How articles frame their subject"
        subtitle={`How the ${formatCount(total)} analysed articles in the last ${windowDays} days split across framing indicators. These describe coverage, not political orientation.`}
      />

      <div className="mt-8">
        {query.isLoading ? (
          <div className="space-y-4">
            <Skeleton className="h-4 w-full rounded-full" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        ) : query.isError ? (
          <ErrorState
            compact
            title="Couldn't load framing"
            error={query.error}
            onRetry={() => query.refetch()}
          />
        ) : total === 0 ? (
          <EmptyState
            title="No framing labels yet"
            message="Enrichment hasn't produced framing labels for this window."
          />
        ) : (
          <>
            {/* Category labels + shares, sitting above the bar. */}
            <div className="flex items-end justify-between gap-4">
              {primary.map((b) => {
                const share = primaryTotal > 0 ? b.count / primaryTotal : 0;
                const meta = FRAMING_META[b.key];
                return (
                  <div key={b.key} className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em]">
                      <span
                        className="inline-block h-2 w-2 rounded-sm"
                        style={{ background: meta.colorVar }}
                      />
                      <span className="text-ink-primary">{meta.label}</span>
                    </div>
                    <div className="tabular mt-1 flex items-baseline gap-2">
                      <span className="font-display text-[1.75rem] font-semibold leading-none text-ink-primary tracking-[-0.02em]">
                        {formatPct(share).replace("%", "")}
                      </span>
                      <span className="text-[13px] font-medium text-ink-muted">%</span>
                      <span className="ml-auto text-[12px] tabular text-ink-muted">
                        {formatCount(b.count)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* The proportional strip. Small gaps between segments. */}
            <ProportionalBar buckets={primary} total={primaryTotal} className="mt-4" />

            {/* Secondary buckets — muted, in a single hairline row. */}
            {secondary.length > 0 ? (
              <div className="mt-5 border-t border-subtle pt-4">
                <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
                  Also present
                </div>
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-[12.5px]">
                  {secondary.map((b) => {
                    const meta = FRAMING_META[b.key];
                    const share = total > 0 ? b.count / total : 0;
                    return (
                      <span key={b.key} className="inline-flex items-center gap-2 text-ink-secondary">
                        <span
                          className="inline-block h-1.5 w-1.5 rounded-full"
                          style={{ background: meta.colorVar }}
                        />
                        <span className="text-ink-primary">{meta.label}</span>
                        <span className="tabular text-ink-muted">
                          {formatCount(b.count)} · {formatPct(share)}
                        </span>
                      </span>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}

/**
 * A single stacked bar — one segment per bucket, sized by proportion.
 * Small transparent gaps between segments keep the divisions clean.
 */
function ProportionalBar({
  buckets,
  total,
  className,
}: {
  buckets: Bucket[];
  total: number;
  className?: string;
}) {
  if (total === 0) return null;
  return (
    <div
      className={cn("flex h-2.5 w-full overflow-hidden rounded-full bg-surface-inset", className)}
      role="img"
      aria-label="Framing distribution across analysed articles"
    >
      {buckets.map((b, i) => {
        const pct = (b.count / total) * 100;
        if (pct <= 0) return null;
        const meta = FRAMING_META[b.key];
        return (
          <span
            key={b.key}
            title={`${meta.label}: ${formatCount(b.count)} (${formatPct(b.count / total)})`}
            className={cn(
              "block h-full",
              i > 0 && "border-l-2 border-canvas",
            )}
            style={{
              width: `${pct}%`,
              background: meta.colorVar,
              transition: "width 380ms cubic-bezier(0.22, 0.61, 0.36, 1)",
            }}
          />
        );
      })}
    </div>
  );
}

function partition(raw: { label: string; count: number }[]): {
  primary: Bucket[];
  secondary: Bucket[];
  total: number;
} {
  const counts: Record<FramingLabel, number> = {
    critical: 0,
    neutral: 0,
    supportive: 0,
    mixed: 0,
    insufficient: 0,
    unlabeled: 0,
  };
  const allLabels = [...PRIMARY, ...SECONDARY];
  for (const b of raw) {
    const key = (allLabels.includes(b.label as FramingLabel)
      ? (b.label as FramingLabel)
      : "unlabeled") as FramingLabel;
    counts[key] += b.count;
  }
  const primary = PRIMARY.map((k) => ({ key: k, count: counts[k] }));
  const secondary = SECONDARY.filter((k) => counts[k] > 0).map((k) => ({
    key: k,
    count: counts[k],
  }));
  const total = allLabels.reduce((s, k) => s + counts[k], 0);
  return { primary, secondary, total };
}
