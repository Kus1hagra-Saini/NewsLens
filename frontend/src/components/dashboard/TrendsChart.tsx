import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SectionHeader } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { formatCount, formatDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useTrends } from "@/api/queries";
import type { TimeSeriesPoint } from "@/api/types";

const WINDOWS = [7, 14, 30, 90] as const;
type WindowDays = (typeof WINDOWS)[number];

/**
 * Coverage volume over time. Editorial layout — the chart sits on the
 * page directly (no card wrapper), with a small window selector on the
 * right of the section header and a totals summary line below the chart.
 */
export function TrendsChart() {
  const [window, setWindow] = useState<WindowDays>(7);
  const query = useTrends(window);

  const merged = useMemo(() => mergePoints(query.data), [query.data]);
  const hasData = merged.length > 0;
  const totalArticles = merged.reduce((s, p) => s + p.articles, 0);
  const totalStories = query.data?.stories_per_day.reduce((s, p) => s + p.count, 0) ?? 0;

  return (
    <section className="reveal-up reveal-d2">
      <SectionHeader
        kicker="Coverage volume"
        title="How much India is publishing"
        subtitle="Articles and clustered stories per day across every monitored outlet, bucketed daily in UTC."
        action={<WindowSelector value={window} onChange={setWindow} />}
      />

      <div className="mt-6 h-[300px]">
        {query.isLoading ? (
          <Skeleton className="h-full w-full rounded-md" />
        ) : query.isError ? (
          <ErrorState
            compact
            title="Couldn't load trends"
            error={query.error}
            onRetry={() => query.refetch()}
          />
        ) : !hasData ? (
          <EmptyState
            title="No coverage in this window"
            message="No articles have been ingested in the selected window."
          />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={merged}
              margin={{ top: 12, right: 4, left: -12, bottom: 4 }}
            >
              <defs>
                <linearGradient id="areaArticles" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="rgb(var(--color-accent))" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="rgb(var(--color-accent))" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="areaStories" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="rgb(var(--color-framing-supportive))" stopOpacity={0.18} />
                  <stop offset="100%" stopColor="rgb(var(--color-framing-supportive))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="0"
                stroke="rgb(var(--color-hairline))"
                strokeOpacity={0.08}
                vertical={false}
              />
              <XAxis
                dataKey="date"
                tickFormatter={(d) => formatDate(d)}
                tick={{ fontSize: 11, fill: "rgb(var(--color-ink-muted))" }}
                axisLine={{ stroke: "rgb(var(--color-hairline))", strokeOpacity: 0.15 }}
                tickLine={false}
                minTickGap={28}
                dy={4}
              />
              <YAxis
                allowDecimals={false}
                width={44}
                tick={{ fontSize: 11, fill: "rgb(var(--color-ink-muted))" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ stroke: "rgb(var(--color-ink-primary))", strokeOpacity: 0.15, strokeWidth: 1 }}
                content={<TrendsTooltip />}
              />
              <Area
                type="monotone"
                name="Articles"
                dataKey="articles"
                stroke="rgb(var(--color-accent))"
                strokeWidth={2}
                fill="url(#areaArticles)"
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "rgb(var(--color-surface))" }}
                animationDuration={480}
              />
              <Area
                type="monotone"
                name="Stories"
                dataKey="stories"
                stroke="rgb(var(--color-framing-supportive))"
                strokeWidth={1.75}
                strokeDasharray="4 3"
                fill="url(#areaStories)"
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "rgb(var(--color-surface))" }}
                animationDuration={480}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {hasData ? (
        <div className="mt-2 flex flex-wrap items-baseline justify-between gap-y-2 border-t border-ink-primary/10 pt-3 text-[12px] text-ink-muted">
          <div className="flex items-center gap-5">
            <LegendDot color="rgb(var(--color-accent))" label={`${formatCount(totalArticles)} articles`} />
            <LegendDot
              color="rgb(var(--color-framing-supportive))"
              label={`${formatCount(totalStories)} stories`}
              dashed
            />
          </div>
          <span className="tabular">
            Last {window} days · bucketed daily (UTC)
          </span>
        </div>
      ) : null}
    </section>
  );
}

function LegendDot({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 text-ink-secondary">
      <span
        className={cn(
          "inline-block h-[3px] w-4 rounded-full",
          dashed && "opacity-80",
        )}
        style={{
          background: dashed
            ? `repeating-linear-gradient(to right, ${color} 0 4px, transparent 4px 7px)`
            : color,
        }}
      />
      <span className="tabular font-medium text-ink-primary">{label}</span>
    </span>
  );
}

function WindowSelector({
  value,
  onChange,
}: {
  value: WindowDays;
  onChange: (n: WindowDays) => void;
}) {
  return (
    <div
      className="inline-flex items-center gap-0.5 text-[11px] font-semibold uppercase tracking-[0.12em]"
      role="tablist"
      aria-label="Trend window"
    >
      <span className="mr-2 hidden text-ink-muted md:inline">Window</span>
      {WINDOWS.map((w) => {
        const active = w === value;
        return (
          <button
            key={w}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(w)}
            className={cn(
              "tabular h-7 rounded-sm px-2.5",
              "transition-all duration-150 ease-soft",
              active
                ? "text-ink-primary underline underline-offset-[6px] decoration-2 decoration-accent"
                : "text-ink-muted hover:text-ink-primary",
            )}
          >
            {w}D
          </button>
        );
      })}
    </div>
  );
}

interface TooltipPayload {
  color?: string;
  name?: string;
  value?: number;
  dataKey?: string;
}

function TrendsTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-md border border-subtle bg-surface px-3 py-2.5 shadow-pop">
      <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
        {formatDate(label)}
      </div>
      <div className="space-y-1">
        {payload.map((row) => (
          <div key={row.dataKey} className="flex items-center gap-3 text-[12.5px]">
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: row.color }}
            />
            <span className="text-ink-secondary">{row.name}</span>
            <span className="tabular ml-auto font-semibold text-ink-primary">
              {formatCount(row.value ?? 0)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

interface MergedPoint {
  date: string;
  articles: number;
  stories: number;
}

function mergePoints(
  data: { articles_per_day: TimeSeriesPoint[]; stories_per_day: TimeSeriesPoint[] } | undefined,
): MergedPoint[] {
  if (!data) return [];
  const map = new Map<string, MergedPoint>();
  for (const p of data.articles_per_day) {
    map.set(p.date, { date: p.date, articles: p.count, stories: 0 });
  }
  for (const p of data.stories_per_day) {
    const existing = map.get(p.date);
    if (existing) existing.stories = p.count;
    else map.set(p.date, { date: p.date, articles: 0, stories: p.count });
  }
  return [...map.values()].sort((a, b) => a.date.localeCompare(b.date));
}
