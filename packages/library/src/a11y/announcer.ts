/**
 * Announcer — Spec E Wave 2 accessibility infrastructure.
 *
 * Module-level publish-subscribe store that backs the `<LiveRegion />`
 * component. `announce(text, urgency?)` writes to the store from anywhere
 * (React or non-React — workflow dispatchers, toasts, page transitions);
 * `<LiveRegion />` subscribes and renders the live text into a visually
 * hidden `aria-live` div that assistive tech reads aloud.
 *
 * Design choices:
 *   - Singleton store, so a workflow dispatcher can call `announce()`
 *     without threading a context down.
 *   - Message auto-clears after CLEAR_AFTER_MS so consecutive identical
 *     announcements are re-read by SRs (which only re-announce on text
 *     change).
 *   - Pre-mount announcements are held as pending and delivered on the
 *     first subscription so early workflow fires aren't lost.
 *   - No-op when there are no subscribers AND no LiveRegion has ever
 *     mounted (test-safe; won't crash SSR).
 */

export type LiveUrgency = "polite" | "assertive";

type Listener = (text: string, urgency: LiveUrgency) => void;

const CLEAR_AFTER_MS = 150;

interface StoreState {
  listeners: Set<Listener>;
  // Last announcement per channel — used to re-emit to a listener that
  // subscribes after `announce()` fires (workflow-dispatch-before-mount).
  pending: { polite: string; assertive: string };
  // Timer handles per channel so we can cancel/replace cleanly.
  clearTimers: { polite: ReturnType<typeof setTimeout> | null;
                 assertive: ReturnType<typeof setTimeout> | null };
}

const store: StoreState = {
  listeners: new Set(),
  pending: { polite: "", assertive: "" },
  clearTimers: { polite: null, assertive: null },
};

function _clearTimer(urgency: LiveUrgency): void {
  const t = store.clearTimers[urgency];
  if (t !== null) {
    clearTimeout(t);
    store.clearTimers[urgency] = null;
  }
}

function _scheduleClear(urgency: LiveUrgency): void {
  _clearTimer(urgency);
  store.clearTimers[urgency] = setTimeout(() => {
    store.pending[urgency] = "";
    store.listeners.forEach((fn) => fn("", urgency));
    store.clearTimers[urgency] = null;
  }, CLEAR_AFTER_MS);
}

/**
 * Announce text to assistive technology. `polite` (default) waits until
 * the SR is idle; `assertive` interrupts. Called from React or non-React
 * code — safe to call before any LiveRegion has mounted.
 */
export function announce(
  text: string,
  urgency: LiveUrgency = "polite",
): void {
  const clean = (text ?? "").trim();
  if (clean === "") return;
  store.pending[urgency] = clean;
  store.listeners.forEach((fn) => fn(clean, urgency));
  _scheduleClear(urgency);
}

/**
 * Subscribe to announcements. Returns an unsubscribe function.
 * On subscription, immediately fires any pending message so a listener
 * that mounts after an early `announce()` still surfaces the text.
 */
export function subscribe(fn: Listener): () => void {
  store.listeners.add(fn);
  if (store.pending.polite) fn(store.pending.polite, "polite");
  if (store.pending.assertive) fn(store.pending.assertive, "assertive");
  return () => {
    store.listeners.delete(fn);
  };
}

/**
 * Test-only reset. Clears listeners, pending state, and any scheduled
 * clear timers. Consumers other than tests must not call this — the
 * name is deliberately warty.
 */
export function __resetAnnouncerForTests(): void {
  _clearTimer("polite");
  _clearTimer("assertive");
  store.listeners.clear();
  store.pending.polite = "";
  store.pending.assertive = "";
}
