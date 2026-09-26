import type { ReactNode } from "react";
import { API_BASE_URL, ApiError } from "@/api/client";
import { Button } from "./Button";
import { IconAlert, IconInfo } from "./Icon";

/**
 * Full-height error surface. Never generic: shows the request URL, the
 * status code (or "network"), and whatever detail the server or fetch
 * error gave us. The user's next step is always visible: what call
 * failed, why, and one Retry button.
 */
export function ErrorState({
  title = "Couldn't load data",
  error,
  onRetry,
  compact,
}: {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const info = describeError(error);

  return (
    <div
      className={
        compact
          ? "flex flex-col items-start gap-3 py-5 text-left"
          : "flex flex-col items-center justify-center gap-4 py-14 text-center"
      }
    >
      <div className="grid h-10 w-10 place-items-center rounded-full bg-framing-critical-tint text-framing-critical">
        <IconAlert size={18} />
      </div>
      <div className={compact ? "space-y-1" : "max-w-md space-y-1"}>
        <h3 className="text-[15px] font-semibold text-ink-primary">{title}</h3>
        {info.summary ? (
          <p className="text-[13px] text-ink-secondary">{info.summary}</p>
        ) : null}
      </div>

      {/* Diagnostic strip — always shown so the user knows what to look
          at (Network tab, backend logs, .env base URL). */}
      <dl
        className={
          "grid w-full gap-y-1 text-[12px] " +
          (compact ? "max-w-none" : "max-w-md")
        }
      >
        {info.rows.map((r) => (
          <div
            key={r.label}
            className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3"
          >
            <dt className="text-ink-muted uppercase tracking-[0.06em] text-[10.5px] font-medium self-center">
              {r.label}
            </dt>
            <dd className="tabular break-all text-ink-secondary">{r.value}</dd>
          </div>
        ))}
      </dl>

      {info.hint ? (
        <p className={"text-[11.5px] leading-relaxed text-ink-muted " + (compact ? "" : "max-w-md")}>
          {info.hint}
        </p>
      ) : null}

      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title = "No data yet",
  message = "NewsLens hasn't collected enough data for this view.",
  action,
}: {
  title?: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <div className="grid h-10 w-10 place-items-center rounded-full bg-surface-alt text-ink-muted">
        <IconInfo size={18} />
      </div>
      <div className="max-w-sm space-y-1">
        <h3 className="text-[15px] font-semibold text-ink-primary">{title}</h3>
        <p className="text-[13px] text-ink-muted">{message}</p>
      </div>
      {action}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error → diagnostic-row projection.
// Kept pure so it's cheap to run on every render and easy to unit-test.
// ---------------------------------------------------------------------------
interface DiagRow {
  label: string;
  value: string;
}
interface DiagInfo {
  summary: string;
  rows: DiagRow[];
  hint?: string;
}

function describeError(error: unknown): DiagInfo {
  if (error instanceof ApiError) {
    const shortUrl = error.url.replace(API_BASE_URL, "") || error.url;
    const rows: DiagRow[] = [
      { label: "Endpoint", value: `GET ${shortUrl}` },
      { label: "Base URL", value: API_BASE_URL },
    ];

    if (error.kind === "network") {
      rows.push({ label: "Status", value: "no response (network/CORS)" });
      if (error.detail) rows.push({ label: "Detail", value: error.detail });
      return {
        summary: "The request never reached a response.",
        rows,
        hint:
          "The backend may be down, on a different port, or blocking this " +
          "origin via CORS. Check that FastAPI is running at the Base URL " +
          "above and that its CORS_ORIGINS includes this app's origin.",
      };
    }

    if (error.kind === "parse") {
      rows.push({ label: "Status", value: `${error.status} (non-JSON body)` });
      if (error.detail) rows.push({ label: "Detail", value: error.detail });
      return {
        summary: "Server responded, but the body wasn't valid JSON.",
        rows,
        hint:
          "Usually means the request hit the wrong URL (a dev-server " +
          "index.html, a proxy landing page). Verify the Base URL points " +
          "at the FastAPI process.",
      };
    }

    rows.push({ label: "Status", value: String(error.status) });
    if (error.detail) rows.push({ label: "Detail", value: error.detail });
    return {
      summary: httpSummary(error.status),
      rows,
    };
  }

  return {
    summary: "An unexpected error occurred.",
    rows: [
      { label: "Message", value: error instanceof Error ? error.message : String(error) },
    ],
  };
}

function httpSummary(status: number): string {
  if (status === 404) return "Endpoint not found on the backend.";
  if (status === 422) return "The backend rejected the request parameters.";
  if (status >= 500) return "The backend hit an internal error.";
  if (status >= 400) return "The backend rejected the request.";
  return `The backend returned status ${status}.`;
}
