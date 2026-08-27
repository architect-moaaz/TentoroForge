/**
 * Post-dispatch feedback runner for Form (and, in a follow-up, for Button).
 *
 * When a workflow-dispatching form succeeds or fails, the runtime calls
 * `runOutcome(action, kind)` with the caller-supplied outcome descriptor.
 * The runner shows a toast via sonner (which the standalone-app template
 * already ships with, wrapped in Providers) and navigates to a URL via
 * `window.location.href` — no router dependency, works in every generated
 * app framework.
 *
 * Design choices:
 *  - sonner is loaded LAZILY through a runtime require guarded by
 *    try/catch. That lets the library still build + tree-shake cleanly
 *    when consumers don't have sonner installed (the editor, tests, or
 *    a hand-rolled host app). Failure to load falls back to console.info
 *    so the outcome is still visible when debugging.
 *  - navigate uses `window.location.href` on purpose. `next/navigation`'s
 *    `useRouter` is a hook and can't be called from an event handler
 *    reliably across React versions; a plain full-page navigation is
 *    universal, matches the "form submitted, take me back to the list"
 *    mental model, and picks up any layout-level revalidation.
 *  - SSR safe: guards on `typeof window` so nothing throws when this
 *    module happens to be evaluated on the server.
 */

export type FormOutcomeAction = {
  navigate?: string;
  toast?: string;
};

export type OutcomeKind = "success" | "error";

/** Show the toast + navigate for a given outcome. No-op when both fields
 *  are absent. Safe to call inside try/catch — this function itself never
 *  throws. */
export function runOutcome(action: FormOutcomeAction | undefined, kind: OutcomeKind): void {
  if (!action) return;
  const { toast: toastMsg, navigate } = action;

  if (toastMsg) {
    _showToast(toastMsg, kind);
  }
  if (navigate && typeof window !== "undefined") {
    // Defer the redirect one microtask so the toast has a chance to
    // register before the page unloads.
    setTimeout(() => {
      window.location.href = navigate;
    }, 50);
  }
}

function _showToast(message: string, kind: OutcomeKind): void {
  if (typeof window === "undefined") return;
  try {
    // Runtime-only import guarded so bundlers that can't resolve sonner
    // in the editor context don't fail. Deno/Node bundlers see this as
    // an untyped `require` at runtime — never at compile time.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const sonner = (globalThis as any).require
      ? (globalThis as any).require("sonner")
      : undefined;
    if (sonner && typeof sonner.toast === "function") {
      if (kind === "success" && typeof sonner.toast.success === "function") {
        sonner.toast.success(message);
      } else if (kind === "error" && typeof sonner.toast.error === "function") {
        sonner.toast.error(message);
      } else {
        sonner.toast(message);
      }
      return;
    }
  } catch {
    // fall through to the console fallback
  }
  // ESM path: try dynamic import. Won't await — fire-and-forget so the
  // navigate microtask isn't blocked. Sonner resolves synchronously in
  // apps that have it installed.
  try {
    // Dynamic import at runtime; the module specifier is a plain string
    // so bundlers that can't statically resolve `sonner` (e.g. the editor
    // context) don't break. `any` on the promise suppresses the type
    // resolution failure without needing @ts-expect-error.
    (import("sonner" as any) as Promise<any>).then((m: any) => {
      if (m && typeof m.toast === "function") {
        if (kind === "success" && typeof m.toast.success === "function") {
          m.toast.success(message);
        } else if (kind === "error" && typeof m.toast.error === "function") {
          m.toast.error(message);
        } else {
          m.toast(message);
        }
      } else {
        // eslint-disable-next-line no-console
        console.info(`[toast:${kind}] ${message}`);
      }
    }).catch(() => {
      // eslint-disable-next-line no-console
      console.info(`[toast:${kind}] ${message}`);
    });
  } catch {
    // eslint-disable-next-line no-console
    console.info(`[toast:${kind}] ${message}`);
  }
}

/** Derive a sensible "go back to the parent list" URL from the current
 *  window location. Used as the runtime default when the schema didn't
 *  set an explicit onSuccess.navigate.
 *
 *   /candidates/new           → /candidates
 *   /candidates/[id]/edit     → /candidates/[id]
 *   /schedule-assessment      → /                (single-segment → root)
 *   /                         → /                (already at root)
 */
export function parentPath(pathname?: string): string {
  const raw = pathname ?? (typeof window !== "undefined" ? window.location.pathname : "/");
  const clean = raw.split(/[?#]/)[0]; // drop query/hash
  const parts = clean.split("/").filter(Boolean);
  if (parts.length <= 1) return "/";
  return "/" + parts.slice(0, -1).join("/");
}

/** Merge a caller-supplied FormOutcomeAction with sensible defaults so a
 *  schema that omits both `toast` and `navigate` still gets some feedback.
 *  Defaults are only applied per field — caller values always win. */
export function withDefaults(
  action: FormOutcomeAction | undefined,
  defaults: FormOutcomeAction,
): FormOutcomeAction {
  const src = action || {};
  return {
    toast: src.toast ?? defaults.toast,
    navigate: src.navigate ?? defaults.navigate,
  };
}
