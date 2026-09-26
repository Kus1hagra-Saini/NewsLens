import { formatRelative } from "@/lib/format";
import { IconCircleCheck, IconClock } from "@/components/ui/Icon";
import type { LatestIngestionRun } from "@/api/types";
import { cn } from "@/lib/cn";

/**
 * Editorial masthead. Not a card, not a hero — a newspaper-style header
 * with a thin rule above and below, tiny masthead metadata, a large
 * display headline, and a compact live-status chip on the right.
 *
 * The wording is deliberately editorial rather than product-marketing:
 *   "See how the news is being covered."
 * followed by a single-sentence explainer.
 */
export function DashboardHeader({
  latestRun,
  loading,
}: {
  latestRun: LatestIngestionRun | null | undefined;
  loading: boolean;
}) {
  return (
    <header className="reveal-up">
      {/* Masthead strip — small caps, date-line style. */}
      <div className="mb-8 flex flex-wrap items-baseline justify-between gap-y-2 border-t-2 border-ink-primary pt-3 text-[10.5px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
        <div className="flex items-center gap-3">
          <span className="text-ink-primary">The NewsLens Desk</span>
          <span className="hidden sm:inline text-ink-muted/50">/</span>
          <span className="hidden sm:inline">Comparative coverage &amp; framing</span>
        </div>
        <div className="tabular text-ink-muted">{todayLabel()}</div>
      </div>

      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div className="max-w-3xl">
          <h1 className="font-display text-display-xl leading-[1.05] tracking-[-0.02em] text-ink-primary sm:text-display-2xl">
            <span>See how the news</span>{" "}
            <span className="italic text-accent">is being covered</span>
            <span>.</span>
          </h1>
          <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-ink-secondary">
            NewsLens compares coverage across monitored Indian outlets and
            surfaces measurable differences in framing, emphasis and source
            distribution — grounded in the article itself, not the outlet&rsquo;s
            reputation.
          </p>
        </div>

        <StatusChip latestRun={latestRun ?? null} loading={loading} />
      </div>
    </header>
  );
}

function todayLabel(): string {
  const d = new Date();
  return d
    .toLocaleDateString("en-IN", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    })
    .toUpperCase();
}

function StatusChip({
  latestRun,
  loading,
}: {
  latestRun: LatestIngestionRun | null;
  loading: boolean;
}) {
  if (loading) {
    return <div className="h-[52px] w-56 shrink-0 animate-pulse-soft rounded-md bg-surface-alt" />;
  }
  if (!latestRun) return null;

  const isOk = latestRun.status === "success";
  const isFailed = latestRun.status === "failed";
  const isRunning = latestRun.status === "running";
  const Icon = isOk ? IconCircleCheck : IconClock;
  const tone = isFailed
    ? "text-framing-critical"
    : isRunning
    ? "text-accent"
    : isOk
    ? "text-framing-supportive"
    : "text-ink-muted";

  return (
    <div
      className={cn(
        "shrink-0 flex items-center gap-3",
        "border-l-2 border-ink-primary/10 pl-4",
      )}
      title={`Ingestion run #${latestRun.id} · ${latestRun.status}`}
    >
      <span className={cn("grid h-8 w-8 place-items-center rounded-full bg-surface-alt", tone)}>
        <Icon size={15} />
      </span>
      <div className="min-w-0">
        <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
          Last ingestion
        </div>
        <div className="tabular text-[13.5px] font-medium text-ink-primary">
          {formatRelative(latestRun.completed_at ?? latestRun.started_at)}
          <span className="text-ink-muted"> · run #{latestRun.id}</span>
        </div>
      </div>
    </div>
  );
}
