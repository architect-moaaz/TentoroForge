/**
 * What this application tells Forge when it breaks, or when it drags.
 *
 * The owner of a generated application is the only telemetry Forge has. They
 * can type "it crashed" and "it's really slow", and until this module carried
 * something back, both sentences reached nothing — Smith could only paraphrase
 * the complaint. Every catch site in the runtime (workflow db_update,
 * db_insert, db_delete, the API routes, the render boundaries) calls
 * `reportRuntimeException`; the two API routes an app's own controls hit call
 * `measured` and report what took too long.
 *
 * Configuration comes from env vars at startup:
 *   FORGE_URL         — e.g. http://localhost:6500 (backend base URL)
 *   FORGE_PROJECT_ID  — the uuid of THIS generated app's project row
 *   FORGE_SLOW_MS     — what "slow" means here (default 2000)
 *
 * The first two are seeded by the generator into .env / .env.local when the
 * app is created. Missing config = the reporter no-ops silently (dev
 * environments without a Forge running still boot fine).
 *
 * ── WHAT IS SENT, AND WHAT MUST NOT BE ────────────────────────────────────
 *
 * A crash payload can carry a customer's data — an order, a diagnosis, a
 * name — and that data belongs to the owner of this application, not to the
 * platform that generated it. Two rules hold, and both are STRUCTURAL: they
 * are properties of what this file can reach, not filters that look at
 * content and decide. A filter is a list of exceptions waiting to be wrong.
 *
 *  1. VALUES NEVER LEAVE. A report carries the NAMES of the things involved —
 *     the route pattern, the control's label, the workflow, the step, and the
 *     KEYS of the payload a control sent. Never a value. `payload_keys` is
 *     produced by `Object.keys` at the call site and the object itself is
 *     never carried into this module, so there is nothing here to leak.
 *     There is no `request_body` and no `user_context`: both used to be sent
 *     whole, and both were a customer's record on the wire.
 *
 *  2. THE ROUTE IS A PATTERN, NOT A URL. `/cases/8f2a…` is a record id and
 *     `?q=jane@…` is a customer. `routePattern` matches the browser's path
 *     against the routes THIS application declares (src/lib/incident-map.ts,
 *     written from the same dispatch contract the build-time dry run uses)
 *     and sends the pattern it matched — `/cases/[id]`. A path that matches
 *     nothing declared is not sent at all. The query string is never read.
 *
 * The one thing that cannot be made structural is the exception MESSAGE: a
 * database driver writes the offending value into its own text
 * (`duplicate key … (email)=(…)`) and no rule about our code prevents that.
 * It is sent, because a crash without its message is unactionable — and it is
 * why the report lands in the project's own directory beside its run ledger
 * and nowhere else.
 *
 * ── HOW OFTEN ─────────────────────────────────────────────────────────────
 *
 * Crashes coalesce: the same error firing a hundred times in a loop is one
 * thing to fix, so identical reports inside a short window are dropped and
 * the count is carried on the next one that gets through.
 *
 * Slow responses do NOT coalesce. For a crash a repeat adds nothing; for
 * slowness the repeats ARE the measurement — an average over four
 * observations is a different fact from an average over four hundred — so
 * every observation past the threshold is sent, and the ledger does the
 * arithmetic.
 */

import { ROUTES, CONTROLS } from "@/lib/incident-map";

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
  /** The action type of the step that threw — `send_email`, `db_insert`. */
  action_type?: string;
  /** A ROUTE PATTERN. Never a concrete path: see `routePattern`. */
  page_route?: string;
  /** The control that started this, e.g. `Table.rowActions[0]`. */
  control?: string;
  /** Its visible text, which is the owner's own wording. */
  control_label?: string;
  /** The NAMES of the keys a control put on the wire. Never the values. */
  payload_keys?: string[];
  /** The acting role — the owner's own vocabulary, never a user identity. */
  role?: string;
}

export interface SlowResponseReport {
  /** What was being done: a workflow id, or a data operation name. */
  operation: string;
  ms: number;
  workflow_id?: string;
  entity?: string;
  page_route?: string;
  control?: string;
  control_label?: string;
  role?: string;
}

const FORGE_URL = process.env.FORGE_URL ?? "";
const FORGE_PROJECT_ID = process.env.FORGE_PROJECT_ID ?? "";

/** What this application calls slow, in milliseconds. Declared rather than
 *  discovered: a threshold that moved with the measurement would make every
 *  answer about it unfalsifiable. It rides along in every slow report, so a
 *  reading of the ledger always knows what it was measured against. */
export const SLOW_MS = Number(process.env.FORGE_SLOW_MS) || 2000;

function endpoint(suffix: string): string {
  return `${FORGE_URL.replace(/\/$/, "")}/api/projects/${FORGE_PROJECT_ID}/${suffix}`;
}

/** Fire-and-forget POST. A report failure MUST NOT crash the caller, and a
 *  report must not make the thing it is reporting on slower. */
function send(url: string, payload: unknown): void {
  try {
    fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      // Keep the request alive past page unload / route change so a crash on
      // navigation still gets reported.
      keepalive: true,
    }).catch(() => { /* swallow — never crash on report */ });
  } catch {
    /* fetch itself threw (very rare) — swallow */
  }
}

// ── The route pattern ──────────────────────────────────────────────────────

/**
 * The declared route a concrete path belongs to, or undefined.
 *
 * This is a LOOKUP in the application's own contract, not a guess at what
 * looks like an id: `ROUTES` is written from the same dispatch manifest the
 * build-time dry run reads, so a pattern returned here is a page this
 * application actually ships. Everything else — an id, a query string, a path
 * from some other app sharing the origin — returns undefined and is not sent.
 */
export function routePattern(pathname: string | undefined | null): string | undefined {
  if (!pathname) return undefined;
  const want = pathname.split("?")[0].split("#")[0].replace(/\/+$/, "") || "/";
  const parts = want.split("/");
  for (const route of ROUTES) {
    const candidate = route.replace(/\/+$/, "") || "/";
    const theirs = candidate.split("/");
    if (theirs.length !== parts.length) continue;
    let ok = true;
    for (let i = 0; i < theirs.length; i++) {
      const seg = theirs[i];
      // A `[slug]` segment stands for exactly one segment of any content —
      // and that content is the part we are refusing to send.
      if (seg.startsWith("[") && seg.endsWith("]")) continue;
      if (seg !== parts[i]) { ok = false; break; }
    }
    if (ok) return candidate;
  }
  return undefined;
}

/** Where we are, as a pattern. Server-side there is no location, and the
 *  caller passes the route it already knows. */
function hereAsPattern(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return routePattern(window.location?.pathname);
}

/**
 * The control that runs this workflow, from the application's own dispatch
 * contract — the name and visible label the owner sees, so a crash can be
 * described as "Approve on the case page" rather than as a workflow id.
 *
 * When more than one control runs the same workflow and the route does not
 * say which, nothing is returned: naming the wrong button is worse than
 * naming none.
 */
export function controlFor(
  workflowId: string | undefined, route?: string,
): { control: string; label: string; route: string } | undefined {
  if (!workflowId) return undefined;
  const wired = CONTROLS[workflowId];
  if (!wired || wired.length === 0) return undefined;
  const onRoute = route ? wired.filter((c) => c.route === route) : wired;
  const candidates = onRoute.length ? onRoute : wired;
  return candidates.length === 1 ? candidates[0] : undefined;
}

// ── Crashes ────────────────────────────────────────────────────────────────

// Coalesce identical errors within a short window so a broken loop doesn't
// hammer Forge, and carry what was suppressed on the next one through so the
// count stays true.
const _seenRecently = new Map<string, { at: number; suppressed: number }>();
const _WINDOW_MS = 5_000;

function _fingerprint(r: RuntimeExceptionReport): string {
  return [
    r.kind, (r.message || "").slice(0, 200),
    r.source_file || "", r.source_line ?? "",
    r.workflow_id || "", r.node_id || "",
  ].join("|");
}

/** Send an exception to Forge. Fire-and-forget. */
export function reportRuntimeException(report: RuntimeExceptionReport): void {
  if (!FORGE_URL || !FORGE_PROJECT_ID) return;

  const fp = _fingerprint(report);
  const now = Date.now();
  const last = _seenRecently.get(fp);
  if (last && now - last.at < _WINDOW_MS) {
    last.suppressed += 1;
    return;
  }
  _seenRecently.set(fp, { at: now, suppressed: 0 });
  // Cap the map so we don't leak forever.
  if (_seenRecently.size > 200) {
    const oldest = [..._seenRecently.entries()].sort((a, b) => a[1].at - b[1].at)[0]?.[0];
    if (oldest) _seenRecently.delete(oldest);
  }

  // The control, when the workflow names one and only one. Filled here rather
  // than at every catch site: the runtime knows the workflow, the contract
  // knows the button.
  const route = report.page_route ?? hereAsPattern();
  const wired = report.control ? undefined : controlFor(report.workflow_id, route);

  send(endpoint("runtime-exceptions"), {
    ...report,
    page_route: route,
    control: report.control ?? wired?.control,
    control_label: report.control_label ?? wired?.label,
    occurrences: 1 + (last?.suppressed ?? 0),
  });
}

/** Turn a caught `unknown` into a report shape without the caller having to
 *  type-guard. */
export function reportFromError(
  err: unknown, base: Omit<RuntimeExceptionReport, "message" | "stack">,
): void {
  const message = err instanceof Error ? err.message : String(err);
  const stack = err instanceof Error && err.stack ? err.stack : undefined;
  reportRuntimeException({ ...base, message, stack });
}

// ── Slow responses ─────────────────────────────────────────────────────────

/**
 * Report one server response that took longer than this application calls
 * acceptable. Only ever called with a duration this process measured itself.
 */
export function reportSlowResponse(report: SlowResponseReport): void {
  if (!FORGE_URL || !FORGE_PROJECT_ID) return;
  if (!(report.ms >= SLOW_MS)) return;
  const wired = report.control ? undefined : controlFor(report.workflow_id, report.page_route);
  send(endpoint("incidents"), {
    kind: "slow",
    operation: report.operation,
    ms: Math.round(report.ms),
    thresholdMs: SLOW_MS,
    workflow: report.workflow_id,
    entity: report.entity,
    route: report.page_route,
    control: report.control ?? wired?.control,
    label: report.control_label ?? wired?.label,
    role: report.role,
  });
}

/**
 * Run something and report it if it drags. Returns exactly what it was given
 * to run, and re-throws exactly what that threw — the timing is beside the
 * work, never in front of it.
 *
 * WHAT THIS MEASURES is the duration of a server handler in this process, and
 * nothing else: not the browser's render, not the network between a customer
 * and the server, not a cold start before this code runs. Every answer built
 * on it has to say so, which is why the operation name is carried and not
 * just the number.
 */
export async function measured<T>(
  what: Omit<SlowResponseReport, "ms">, run: () => Promise<T>,
): Promise<T> {
  const t0 = Date.now();
  try {
    return await run();
  } finally {
    reportSlowResponse({ ...what, ms: Date.now() - t0 });
  }
}

// ── Browser bootstrap ──────────────────────────────────────────────────────

/**
 * Client-side bootstrap — installs global window handlers so ANY uncaught
 * error or unhandled rejection in the browser gets reported, not just the
 * workflow-runtime catches. Idempotent + guarded for SSR (module also loads on
 * the server; handlers only install when `window` is defined). Called
 * automatically at module load below.
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
      page_route: hereAsPattern(),
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
      page_route: hereAsPattern(),
    });
  });
}

// Auto-run on import — the module is dropped into src/lib/ and imported
// both by client bundles (providers.tsx) and server code (workflows/index.ts).
// The SSR guard inside bootstrap() means server imports are a no-op.
bootstrapBrowserReporter();
