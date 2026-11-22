/**
 * Crossings, live. One in-memory line per server: the geofence service puts each new crossing here, and every open monitor
 * (api/geofence/stream) hears it. Like the tracking hub, this is per process — behind several servers a monitor sees the
 * crossings its own server handled, and the stored events (forge_geofence_events) are the complete record.
 * Forge runtime — do not remove.
 */
import type { GeofenceEvent } from "./engine";

type Listener = (e: GeofenceEvent) => void;
const g = globalThis as unknown as { __forgeGeofenceListeners?: Set<Listener> };
const listeners: Set<Listener> = (g.__forgeGeofenceListeners ??= new Set());

export function listen(fn: Listener): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export function publishCrossing(e: GeofenceEvent): void {
  for (const fn of [...listeners]) {
    try { fn(e); } catch { /* one broken listener must not stop the others */ }
  }
}

export function listenerCount(): number { return listeners.size; }
