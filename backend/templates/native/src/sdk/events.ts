// The app SDK (native) — in-process events. The web has one: a finished
// workflow dispatches `forge:workflow-done` on `window`, and everything on the
// page that shows data looks again. A phone has no `window`, so the same idea
// is a tiny channel: a module-level list of listeners, nothing to install.
//
// PURE (no react-native import) so the logic that uses it runs under plain
// node in the template's tests.

export type Listener<T> = (payload: T) => void;

export interface Channel<T> {
  emit(payload: T): void;
  /** Returns the function that stops listening. */
  subscribe(listener: Listener<T>): () => void;
}

export function channel<T>(): Channel<T> {
  const listeners = new Set<Listener<T>>();
  return {
    emit(payload) {
      // A copy: a listener that unsubscribes while being told must not skip the next.
      for (const l of [...listeners]) {
        try { l(payload); } catch (err) { console.warn("[forge] an event listener threw:", err); }
      }
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}

/** A workflow finished successfully: every mounted read looks again (the web's
 *  `forge:workflow-done`). `useLive` and pull-to-refresh use it too — "look
 *  again" is one signal, whoever asks. */
export const refreshReads = channel<{ workflowId?: string }>();

/** The server answered 401 to a call that was not part of signing in: the
 *  session is gone. The session provider listens and the app returns to /login. */
export const signedOut = channel<void>();

export type ToastKind = "success" | "error" | "info";
export interface ToastMessage { id: number; kind: ToastKind; title: string; description?: string }

/** What a toast host listens for. `toast.success(...)` from anywhere — a hook,
 *  a screen, a plain function — emits here. */
export const toasts = channel<ToastMessage>();
