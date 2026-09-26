/**
 * Formatters used across the dashboard. Kept side-effect free so
 * charts + KPI cards can share them.
 */

const NF_INT = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});
const NF_COMPACT = new Intl.NumberFormat("en-IN", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const NF_PCT = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 0,
});

export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return NF_INT.format(n);
}

export function formatCompact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n < 10_000) return NF_INT.format(n);
  return NF_COMPACT.format(n);
}

export function formatPct(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  return NF_PCT.format(fraction);
}

const DATE_TIME = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
});
const DATE_ONLY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
});
const DATE_LONG = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export function formatDateTime(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "—";
  return DATE_TIME.format(d);
}

export function formatDate(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "—";
  return DATE_ONLY.format(d);
}

export function formatDateLong(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "—";
  return DATE_LONG.format(d);
}

/**
 * Compact relative time (e.g. "3h ago", "2d ago", "just now").
 * Deliberately uses fixed thresholds; no locale for consistency.
 */
export function formatRelative(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "—";

  const seconds = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(days / 365);
  return `${years}y ago`;
}

/** e.g. framing_score 0.42 → "+0.42". */
export function formatSignedDecimal(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const s = n.toFixed(digits);
  return n > 0 ? `+${s}` : s;
}
