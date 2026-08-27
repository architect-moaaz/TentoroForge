/**
 * Presence client — Spec E Wave 1 runtime primitive.
 *
 * Thin EventSource client for `/api/presence/:route`. Each connected
 * user posts `{userId, name?, avatarUrl?, cursor?, focusedField?}` to
 * the server, and the server broadcasts the deduplicated user roster
 * back to every subscriber for that route.
 *
 * Exposes:
 *  - `subscribePresence(route, cb)` — imperative subscribe (returns
 *    unsubscribe).
 *  - `usePresence(route)` — React hook wrapping the imperative API.
 *  - Registers `window.__forgePresenceHook__` so the pure library
 *    `<PresenceIndicator>` can pull data without a hard dep on
 *    `@forge/renderer`.
 */

import * as React from "react";

export interface PresenceUser {
  userId: string;
  name?: string;
  avatarUrl?: string;
  color?: string;
  cursor?: { x: number; y: number };
  focusedField?: string;
}

type Listener = (users: PresenceUser[]) => void;

interface ChannelState {
  route: string;
  users: PresenceUser[];
  listeners: Set<Listener>;
  source?: EventSource;
  refCount: number;
}

const channels = new Map<string, ChannelState>();

function normalizeRoute(route?: string | null): string {
  if (route && typeof route === "string" && route.trim()) return route.trim();
  if (typeof window !== "undefined" && window.location?.pathname) {
    return window.location.pathname;
  }
  return "/";
}

function openChannel(route: string): ChannelState {
  const existing = channels.get(route);
  if (existing) {
    existing.refCount += 1;
    return existing;
  }
  const state: ChannelState = {
    route,
    users: [],
    listeners: new Set(),
    refCount: 1,
  };
  channels.set(route, state);

  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    return state;
  }

  const url = `/api/presence/${encodeURIComponent(route)}`;
  try {
    const es = new EventSource(url);
    state.source = es;
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as { users?: PresenceUser[] };
        state.users = Array.isArray(payload.users) ? payload.users : [];
        for (const l of state.listeners) l(state.users);
      } catch {
        /* ignore malformed message */
      }
    };
    es.onerror = () => {
      // Let the browser reconnect automatically; nothing to do.
    };
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[presence-client] EventSource failed", err);
  }
  return state;
}

function releaseChannel(route: string): void {
  const state = channels.get(route);
  if (!state) return;
  state.refCount -= 1;
  if (state.refCount > 0) return;
  state.source?.close();
  channels.delete(route);
}

/**
 * Subscribe to presence events for a route. Returns an unsubscribe.
 */
export function subscribePresence(
  route: string | undefined,
  cb: Listener,
): () => void {
  const key = normalizeRoute(route);
  const state = openChannel(key);
  state.listeners.add(cb);
  // Emit the current snapshot synchronously so consumers can render.
  cb(state.users);
  return () => {
    state.listeners.delete(cb);
    releaseChannel(key);
  };
}

/**
 * React hook — returns the current user roster for the given route.
 */
export function usePresence(route?: string): PresenceUser[] {
  const [users, setUsers] = React.useState<PresenceUser[]>([]);
  React.useEffect(() => subscribePresence(route, setUsers), [route]);
  return users;
}

// Bridge: expose the imperative API on window so the pure library
// PresenceIndicator can hydrate without importing @forge/renderer.
if (typeof window !== "undefined") {
  (window as any).__forgePresenceHook__ = subscribePresence;
}
