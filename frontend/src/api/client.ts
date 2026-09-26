/**
 * Thin fetch wrapper for the NewsLens backend.
 *
 * Reads the base URL from ``VITE_API_BASE_URL`` (with ``VITE_API_URL``
 * accepted as a legacy alias so existing .env files keep working) and
 * falls back to ``http://localhost:8000`` during local dev. A
 * production build should always set the env var explicitly.
 *
 * Errors always carry the full URL, HTTP status, and any server-provided
 * ``detail`` string so the UI can render a diagnostic message instead of
 * a generic "something went wrong". Nothing here fabricates fallback
 * data — if the backend is unreachable, the caller sees it.
 */

const RAW_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  (import.meta.env.VITE_API_URL as string | undefined) ??
  "http://localhost:8000";

// Trim trailing slash so path composition is predictable.
export const API_BASE_URL = RAW_BASE.replace(/\/+$/, "");

/**
 * A rich, self-describing error. ``status === 0`` means the request
 * never got a response (network error, CORS block, offline, DNS, etc.).
 * ``kind`` gives the UI a one-word bucket to route on.
 */
export type ApiErrorKind =
  | "network"      // fetch itself threw — CORS, offline, DNS, refused, aborted
  | "http"         // reached the server, got a non-2xx status
  | "parse";       // 2xx response but body was not JSON

export class ApiError extends Error {
  status: number;
  detail: string | undefined;
  url: string;
  kind: ApiErrorKind;

  constructor(
    kind: ApiErrorKind,
    status: number,
    url: string,
    message: string,
    detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
    this.url = url;
  }

  /** Short one-liner: "GET /overview — 500 Internal Server Error". */
  get shortLabel(): string {
    const path = this.url.replace(API_BASE_URL, "") || this.url;
    if (this.kind === "network") return `GET ${path} · network error`;
    if (this.kind === "parse") return `GET ${path} · invalid JSON`;
    return `GET ${path} · ${this.status}`;
  }
}

/** Untyped fetch — internal. Prefer the typed hooks in api/queries.ts. */
export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (err) {
    // Network / CORS / DNS / offline / aborted. Cross-browser fetch
    // does not distinguish these in the thrown error, so we surface the
    // native message verbatim as `detail` and let the UI hint at the
    // likely causes.
    throw new ApiError(
      "network",
      0,
      url,
      "Unable to reach NewsLens backend",
      err instanceof Error ? err.message : String(err),
    );
  }

  if (!res.ok) {
    // Best-effort detail extraction. FastAPI returns { "detail": "..." }
    // on HTTPException, so we surface that as-is when present.
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
      else if (body?.detail !== undefined) detail = JSON.stringify(body.detail);
    } catch {
      // Response body wasn't JSON — try text as a last resort but cap
      // the length so an accidental HTML error page doesn't flood the UI.
      try {
        const txt = (await res.text()).trim();
        if (txt) detail = txt.length > 240 ? txt.slice(0, 240) + "…" : txt;
      } catch {
        /* give up */
      }
    }
    throw new ApiError(
      "http",
      res.status,
      url,
      `Request failed with status ${res.status}`,
      detail,
    );
  }

  // Parse. If the server returned 2xx but the body isn't JSON, we still
  // want a specific error so the UI can hint at "backend returned 200
  // but body is not JSON" (which usually means the wrong URL was hit —
  // a dev-server fallback page, a proxy landing page, etc.).
  try {
    return (await res.json()) as T;
  } catch (err) {
    throw new ApiError(
      "parse",
      res.status,
      url,
      "Response was not valid JSON",
      err instanceof Error ? err.message : String(err),
    );
  }
}
