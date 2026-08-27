'use client';
import { createContext, type ReactNode } from "react";

export type WorkflowDispatch = (
  name: string,
  args?: Record<string, unknown>,
) => void | Promise<void>;

export const WorkflowDispatcherContext = createContext<WorkflowDispatch | undefined>(undefined);

export interface WorkflowDispatchOptions {
  /** Injectable fetch — defaults to the global `fetch`. */
  fetchImpl?: typeof fetch;
  /** Base URL prefix for the workflow API (default ""). */
  apiBase?: string;
  /** Called synchronously before the request is sent. */
  onStart?: (name: string) => void;
  /** Called with the parsed result on a 2xx response with no `error`. */
  onSuccess?: (name: string, result: unknown) => void;
  /** Called with a human-readable message on any failure. */
  onError?: (name: string, message: string) => void;
  /**
   * Spec E Wave 2 — accessibility announcement seam. Template glue
   * passes the library's LiveRegion-backed `announce()` here; every
   * dispatch then auto-emits a polite "…completed" on success and an
   * assertive "…failed: {message}" on error. Runs in addition to
   * onSuccess/onError. Omit to opt out (unit tests, non-a11y hosts).
   *
   * Kept as an injected callback (rather than an internal import from
   * @tentoroforge/library) so the renderer package stays free of that
   * runtime dependency — the same reason `RegistryLike` is duck-typed
   * in dispatch.tsx.
   */
  announce?: (text: string, urgency: "polite" | "assertive") => void;
  /**
   * Fire-and-forget mode. When true, the dispatcher appends `?detach=1`
   * to the execute URL; the server-side route kicks off the workflow
   * and returns HTTP 202 immediately so long-running pipelines (OCR,
   * AI extract, external API calls) don't block the button's onSuccess
   * (toast + navigate). Use for user-initiated "Queue" / "Submit" style
   * flows where the return value isn't consumed by the caller. Default
   * false — keeps synchronous semantics for workflows whose result the
   * UI reads (compute actions, in-flow value passthrough).
   */
  detach?: boolean;
}

/**
 * Humanize a workflow identifier for SR announcement. `createProduct` →
 * `create product`; `approve_leave_request` → `approve leave request`.
 * Kept intentionally minimal — the announcement is a hint, not the UI
 * copy, so lower-casing + splitting on case/underscore is enough.
 */
function _humanizeWorkflowName(name: string): string {
  return name
    // camelCase → camel Case
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    // snake / kebab → space
    .replace(/[_-]+/g, " ")
    .toLowerCase()
    .trim();
}

/**
 * Builds a {@link WorkflowDispatch} that POSTs to the generated app's
 * `/api/workflows/{name}/execute` route with `{ input: args }`.
 *
 * All app-specific concerns (toast, router refresh) are injected via the
 * `onStart` / `onSuccess` / `onError` callbacks so this transport stays free of
 * any UI / routing dependency. The returned dispatch never rejects: failures
 * are routed to `onError`, so awaiting callers can rely on `finally` to clear
 * pending state.
 */
export function createWorkflowDispatch(
  opts: WorkflowDispatchOptions = {},
): WorkflowDispatch {
  const { fetchImpl, apiBase = "", onStart, onSuccess, onError, announce, detach } = opts;
  return async (name, args) => {
    if (!name) return;
    onStart?.(name);
    const doFetch = fetchImpl ?? fetch;
    // Cached per-dispatch so success + failure announcements share the
    // same humanized label (and we don't recompute on the hot path).
    const _human = announce ? _humanizeWorkflowName(name) : "";
    const _qs = detach ? "?detach=1" : "";
    try {
      const res = await doFetch(
        `${apiBase}/api/workflows/${encodeURIComponent(name)}/execute${_qs}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ input: args ?? {} }),
        },
      );
      const result = await res.json().catch(() => ({}));
      // A workflow run can come back HTTP 200 with `status: "failed"` (the
      // engine catches node throws and reports them in the result body).
      // Treat that as a failure too — otherwise the button fires its
      // success toast + navigation on a run that did nothing.
      const _failed =
        Boolean((result as { error?: unknown }).error) ||
        (result as { status?: string }).status === "failed";
      if (!res.ok || _failed) {
        const message =
          (result && (result as { error?: string }).error) ||
          `Workflow failed (${res.status})`;
        onError?.(name, message);
        announce?.(`${_human} failed: ${message}`, "assertive");
        return;
      }
      onSuccess?.(name, result);
      announce?.(`${_human} completed`, "polite");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(name, msg);
      announce?.(`${_human} failed: ${msg}`, "assertive");
    }
  };
}

export function WorkflowDispatcherProvider({
  dispatch,
  children,
}: {
  dispatch: WorkflowDispatch;
  children: ReactNode;
}) {
  return (
    <WorkflowDispatcherContext.Provider value={dispatch}>
      {children}
    </WorkflowDispatcherContext.Provider>
  );
}
