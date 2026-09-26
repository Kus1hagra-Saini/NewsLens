import { Skeleton } from "@/components/ui/Skeleton";
import { formatCompact } from "@/lib/format";
import type { DashboardOverview } from "@/api/types";
import { cn } from "@/lib/cn";

interface Kpi {
  label: string;
  value: number | null;
  hint?: string;
}

/**
 * The four coverage-snapshot numbers — set inline as a data strip
 * rather than four boxed cards. Large tabular display numerals separated
 * by hairlines, with a small kicker line at the top.
 *
 * All values come straight from /overview; we never fabricate trend
 * arrows or "+X%" figures.
 */
export function KpiRow({
  data,
  loading,
}: {
  data: DashboardOverview | undefined;
  loading: boolean;
}) {
  const kpis: Kpi[] = data
    ? [
        {
          label: "Articles",
          value: data.article_count,
          hint: data.articles_last_24h > 0
            ? `+${formatCompact(data.articles_last_24h)} in 24h`
            : "ingested",
        },
        {
          label: "Stories",
          value: data.story_count,
          hint: data.stories_last_24h > 0
            ? `+${formatCompact(data.stories_last_24h)} in 24h`
            : "clustered",
        },
        {
          label: "Outlets",
          value: data.active_outlet_count,
          hint: "monitored",
        },
        {
          label: "Analysed",
          value: analysedPct(data),
          hint: analysedHint(data),
          // Rendered as a percent — handled inline below.
        },
      ]
    : [];

  return (
    <div className="reveal-up reveal-d1">
      <div className="mb-3 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
        <span className="inline-block h-[6px] w-[6px] rounded-full bg-accent" />
        <span>Coverage snapshot</span>
      </div>

      <div
        className={cn(
          "grid grid-cols-2 gap-x-6 gap-y-6",
          "md:grid-cols-4 md:gap-x-10",
          "border-y border-ink-primary/10 py-6",
        )}
      >
        {loading || !data
          ? [0, 1, 2, 3].map((i) => <KpiSkeleton key={i} />)
          : kpis.map((k, i) => (
              <KpiCell
                key={k.label}
                {...k}
                isPct={i === 3}
                divider={i > 0}
              />
            ))}
      </div>
    </div>
  );
}

function KpiCell({
  label,
  value,
  hint,
  isPct,
  divider,
}: Kpi & { isPct?: boolean; divider?: boolean }) {
  return (
    <div
      className={cn(
        "min-w-0 md:pl-6",
        divider && "md:border-l md:border-ink-primary/10",
      )}
    >
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
        {label}
      </div>
      <div className="tabular mt-1 flex items-baseline gap-1 text-kpi text-ink-primary sm:text-[3rem]">
        {value === null || value === undefined ? (
          "—"
        ) : isPct ? (
          <>
            <span>{value}</span>
            <span className="text-[1.25rem] font-medium text-ink-muted">%</span>
          </>
        ) : (
          formatCompact(value)
        )}
      </div>
      {hint ? (
        <div className="mt-1 text-[12px] text-ink-muted tabular">{hint}</div>
      ) : null}
    </div>
  );
}

function KpiSkeleton() {
  return (
    <div className="min-w-0 md:pl-6 md:border-l md:border-ink-primary/10 first:md:border-none first:md:pl-0">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-2.5 h-10 w-32" />
      <Skeleton className="mt-2 h-3 w-20" />
    </div>
  );
}

function analysedCount(d: DashboardOverview): number {
  return (d.articles_by_state?.complete ?? 0) + (d.articles_by_state?.analyzed ?? 0);
}
function analysedPct(d: DashboardOverview): number {
  const total = d.article_count;
  if (!total) return 0;
  return Math.round((analysedCount(d) / total) * 100);
}
function analysedHint(d: DashboardOverview): string {
  const analysed = analysedCount(d);
  if (!d.article_count) return "no articles yet";
  if (!analysed) return "no analyses yet";
  return `${formatCompact(analysed)} of ${formatCompact(d.article_count)}`;
}
