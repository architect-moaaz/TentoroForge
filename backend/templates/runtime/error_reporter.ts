/**
 * Runtime error reporter — pipes caught exceptions from this generated
 * app to Forge's ingest endpoint so Smith's self-heal loop can pick
 * them up.
 *
 * Every catch site in the runtime (workflow db_update, db_insert,
 * db_delete, api route middleware) calls `reportRuntimeException(...)`
 * with as much locator context as it has. Forge dedups on content, so
 * the same error firing 100 times only kicks off one heal attempt.
 *
 * Configuration comes from env vars at startup:
 *   FORGE_URL         — e.g. http://localhost:6500 (backend base URL)
 *   FORGE_PROJECT_ID  — the uuid of THIS generated app's project row
 *
 * Both are seeded by the generator into .env / .env.local when the app
 * is created. Missing config = the reporter no-ops silently (dev
 * environments without a Forge running still boot fine).
 */

export type RuntimeExceptionKind =
  | "workflow"
  | "api_route"
  | "page_render"
  | "unhandled";

export interface RuntimeExceptionReport {
  kind: RuntimeExceptionKind;
  message: string;
  stack?: string;
  source_file?: string;
  source_line?: number;
  workflow_id?: string;
  node_id?: string;
  page_route?: string;
  request_url?: string;
  request_method?: string;
  request_body?: Record<string, unknown>;
  user_context?: Record<string, unknown>;
}

const FORGE_URL = process.env.FORGE_URL ?? "";
const FORGE_PROJECT_ID = process.env.FORGE_PROJECT_ID ?? "";

// Coalesce identical errors within a short window so a broken loop
// doesn't hammer Forge. Backend still dedups authoritatively — this
// is a cheap client-side backstop.
const _seenRecently = new Map<string, number>();
const _WINDOW_MS = 5_000;

function _fingerprint(r: RuntimeExceptionReport): string {
  return [
    r.kind, (r.message || "").slice(0, 200),
    r.source_file || "", r.source_line ?? "",
    r.workflow_id || "", r.node_id || "",
  ].join("|");
}

/** Send an exception to Forge. Fire-and-forget — a report failure
 *  MUST NOT crash the caller. */
export function reportRuntimeException(report: RuntimeExceptionReport): void {
  if (!FORGE_URL || !FORGE_PROJECT_ID) return;

  const fp = _fingerprint(report);
  const now = Date.now();
  const last = _seenRecently.get(fp) ?? 0;
  if (now - last < _WINDOW_MS) return;
  _seenRecently.set(fp, now);
  // Cap the map so we don't leak forever.
  if (_seenRecently.size > 200) {
    const oldest = [..._seenRecently.entries()].sort((a, b) => a[1] - b[1])[0]?.[0];
    if (oldest) _seenRecently.delete(oldest);
  }

  const url = `${FORGE_URL.replace(/\/$/, "")}/api/projects/${FORGE_PROJECT_ID}/runtime-exceptions`;
  const body = JSON.stringify(report);

  try {
    fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      // Keep the request alive past page unload / route change so a
      // crash on navigation still gets reported.
      keepalive: true,
    }).catch(() => { /* swallow — never crash on report */ });
  } catch {
    /* fetch itself threw (very rare) — swallow */
  }
}

/** Turn a caught `unknown` into a report shape without the caller
 *  having to type-guard. */
export function reportFromError(
  err: unknown, base: Omit<RuntimeExceptionReport, "message" | "stack">,
): void {
  const message = err instanceof Error ? err.message : String(err);
  const stack = err instanceof Error && err.stack ? err.stack : undefined;
  reportRuntimeException({ ...base, message, stack });
}

/**
 * Client-side bootstrap — installs global window handlers so ANY
 * uncaught error or unhandled rejection in the browser gets reported
 * to Forge, not just the workflow-runtime catches. Idempotent + guarded
 * for SSR (module also loads on the server; handlers only install when
 * `window` is defined). Called automatically at module load below.
 */
let _bootstrapped = false;
export function bootstrapBrowserReporter(): void {
  if (_bootstrapped) return;
  if (typeof window === "undefined") return;
  _bootstrapped = true;

  window.addEventListener("error", (ev) => {
    // `window.error` fires for BOTH real JS exceptions AND resource-load
    // failures (<img>, <script>, <link src=…> that 404 or are blocked).
    // Resource errors have no ev.error, no ev.message, and their target
    // is an Element (not window). Surfacing them as page-level Runtime
    // Errors is wrong — Next 15 dev renders them as "[object Event]"
    // with no stack, blocking the page for a broken image.
    const isResourceLoadError =
      ev.target instanceof Element && ev.target !== (window as unknown as EventTarget);
    if (isResourceLoadError) return;
    if (!ev.error && !ev.message) return;
    reportRuntimeException({
      kind: "unhandled",
      message: (ev.error && ev.error.message) || ev.message || "window.error",
      stack: ev.error && ev.error.stack ? ev.error.stack : undefined,
      source_file: ev.filename || undefined,
      source_line: typeof ev.lineno === "number" ? ev.lineno : undefined,
      page_route: window.location?.pathname,
    });
  }, true);  // capture=true so we see resource errors (they don't bubble) and filter them out

  window.addEventListener("unhandledrejection", (ev) => {
    const reason = (ev as PromiseRejectionEvent).reason;
    const message =
      reason instanceof Error ? reason.message : String(reason ?? "unhandled rejection");
    const stack = reason instanceof Error && reason.stack ? reason.stack : undefined;
    reportRuntimeException({
      kind: "unhandled",
      message,
      stack,
      page_route: window.location?.pathname,
    });
  });
}

// Auto-run on import — the module is dropped into src/lib/ and imported
// both by client bundles (providers.tsx) and server code (workflows/index.ts).
// The SSR guard inside bootstrap() means server imports are a no-op.
bootstrapBrowserReporter();
