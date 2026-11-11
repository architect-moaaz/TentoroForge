"use client";

/**
 * Live tracking — a moving dot on a map, and the phone that moves it.
 *
 *   <LiveTrackingMap entity="Order" trip={order.id} pickup={restaurant} dropoff={home} />
 *       the customer's map: the driver's dot moves by itself as notes arrive
 *   <ShareLocation entity="Order" trip={order.id} />
 *       the driver's button: while on, this device sends where it is
 *
 * The trip is a record of the app's own data (`entity` names its kind). Anyone
 * the app lets open that record may follow it; only the person the record names
 * as being on the move (driverId, courierId, …) may share a position for it.
 *
 * The line is /api/tracking/stream (server-sent events: the browser reconnects
 * by itself). The driver posts to /api/tracking/update. A browser can only
 * send a location while the page is open — background tracking needs the
 * native app (see the native SDK's location.ts).
 */
import * as React from "react";
import type { GeoPoint } from "./geo";
import { MapView, type MapPoint } from "./map";

const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
const STALE_MS = 30_000;

export type LivePosition = GeoPoint & { at: number; heading?: number; speed?: number; stage?: string };

export type LiveTrip = {
  /** Where the driver is, or null before the first note. */
  position: LivePosition | null;
  /** "denied": this person may not follow this trip (or is signed out). */
  state: "connecting" | "live" | "reconnecting" | "ended" | "denied";
  /** True when the newest note is older than 30 s: the driver may have lost signal. */
  stale: boolean;
};

/** Listen to one trip. Stops on its own when the trip ends or the page closes. */
export function useLiveTrip(entity: string, trip: string | null | undefined): LiveTrip {
  const [position, setPosition] = React.useState<LivePosition | null>(null);
  const [state, setState] = React.useState<LiveTrip["state"]>("connecting");
  const [now, setNow] = React.useState(() => Date.now());

  React.useEffect(() => {
    if (!trip) return;
    setPosition(null);
    setState("connecting");
    const line = new EventSource(`${BASE}/api/tracking/stream?entity=${encodeURIComponent(entity)}&trip=${encodeURIComponent(trip)}`);
    let opened = false;
    line.onopen = () => { opened = true; setState("live"); };
    line.onerror = () => {
      // Never opened: the server said no (not signed in, not your trip). Retrying cannot help.
      if (!opened) { setState("denied"); line.close(); return; }
      setState((s) => (s === "ended" ? s : "reconnecting"));
    };
    line.onmessage = (e) => {
      try {
        const f = JSON.parse(e.data);
        if (f.done) { setState("ended"); line.close(); return; }
        setState("live");
        // An older note never replaces a newer one (the line can replay on reconnect).
        setPosition((old) => (old && f.at <= old.at ? old : f));
      } catch { /* a garbled frame is skipped */ }
    };
    return () => line.close();
  }, [entity, trip]);

  // Re-check "stale" every few seconds, without waiting for a new note.
  React.useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(t);
  }, []);

  const stale = !!position && now - position.at > STALE_MS;
  return { position: position && { lat: position.lat, lng: position.lng, at: position.at, heading: position.heading, speed: position.speed, stage: position.stage }, state, stale };
}

export type LiveTrackingMapProps = {
  /** The kind of record the trip is: "Order", "Ride", "Visit". */
  entity: string;
  trip: string | null | undefined;
  /** Where the driver is going first (the customer, for a ride). */
  pickup?: GeoPoint;
  dropoff?: GeoPoint;
  /** Which of the two the driver heads for: follows the trip's stage when omitted. */
  heading?: "pickup" | "dropoff";
  height?: number | string;
  className?: string;
};

export function LiveTrackingMap({ entity, trip, pickup, dropoff, heading, height = 360, className }: LiveTrackingMapProps) {
  const live = useLiveTrip(entity, trip);
  const target = (heading ?? (live.position?.stage === "to_dropoff" ? "dropoff" : "pickup")) === "dropoff" ? dropoff : pickup;

  const points = React.useMemo<MapPoint[]>(() => {
    const out: MapPoint[] = [];
    if (target) out.push({ id: "target", lat: target.lat, lng: target.lng, label: "Destination", tone: "accent" });
    if (live.position)
      out.push({ id: "driver", lat: live.position.lat, lng: live.position.lng, label: live.stale ? "Driver (signal lost)" : "Driver", tone: live.stale ? "muted" : "primary" });
    return out;
  }, [target?.lat, target?.lng, live.position?.lat, live.position?.lng, live.stale]);

  const message =
    live.state === "denied" ? "This trip is not available to you."
    : live.state === "ended" ? "The trip has ended."
    : live.state === "reconnecting" ? "Reconnecting…"
    : !live.position ? "Waiting for the driver to share their location…"
    : live.stale ? "No signal from the driver for a while — showing the last known spot."
    : null;

  return (
    <div className={className}>
      <MapView points={points} keepInView height={height} />
      {message && <p className="mt-2 text-sm text-muted-foreground" role="status">{message}</p>}
    </div>
  );
}

const HOW_OFTEN_MS = 4_000;

/** The driver's side. While `on`, this device posts its position every few seconds. */
export function useShareLocation(entity: string, trip: string | null | undefined, on: boolean, stage?: string) {
  const [error, setError] = React.useState<string | null>(null);
  const [sent, setSent] = React.useState(0);
  const stageRef = React.useRef(stage);
  stageRef.current = stage;

  React.useEffect(() => {
    if (!trip || !on) return;
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setError("This device cannot share a location.");
      return;
    }
    setError(null);
    let lastSent = 0;
    let queue: object[] = []; // notes that could not go out while offline
    let flushing = false;
    const flush = async () => {
      if (flushing) return;
      flushing = true;
      try {
      while (queue.length) {
        const note = queue[0];
        const res = await fetch(`${BASE}/api/tracking/update`, {
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(note),
        });
        if (res.status === 401) throw new Error("Sign in to share your location.");
        if (res.status === 403 || res.status === 404) throw new Error("This trip is not yours to share.");
        if (res.status === 409) throw new Error("This job is over.");
        if (!res.ok && res.status >= 500) return; // server trouble: keep it, try again later
        queue.shift();
        setSent((n) => n + 1);
      }
      } finally {
        flushing = false;
      }
    };
    const id = navigator.geolocation.watchPosition(
      (pos) => {
        const at = Date.now();
        if (at - lastSent < HOW_OFTEN_MS) return;
        lastSent = at;
        queue.push({
          entity, trip, lat: pos.coords.latitude, lng: pos.coords.longitude, at,
          heading: pos.coords.heading ?? undefined, speed: pos.coords.speed ?? undefined,
          accuracy: pos.coords.accuracy, stage: stageRef.current,
        });
        if (queue.length > 50) queue = queue.slice(-50); // a long outage keeps the latest only
        flush().then(() => setError(null), (e) => setError(e instanceof Error ? e.message : "Could not send."))
          .catch(() => setError("Could not send your location — trying again."));
      },
      (err) => setError(
        err.code === err.PERMISSION_DENIED
          ? "Location is blocked — allow it for this site in the browser's settings."
          : "Your location could not be found — move to open sky or check GPS.",
      ),
      { enableHighAccuracy: true, maximumAge: 2_000, timeout: 20_000 },
    );
    return () => {
      navigator.geolocation.clearWatch(id);
    };
  }, [entity, trip, on]);

  return { error, sent };
}

/** One button: start or stop sharing for a trip. Ending the trip tells the customer. */
export function ShareLocation({ entity, trip, stage, className }: { entity: string; trip: string; stage?: string; className?: string }) {
  const [on, setOn] = React.useState(false);
  const { error, sent } = useShareLocation(entity, trip, on, stage);

  const stop = async (finish: boolean) => {
    setOn(false);
    if (finish)
      await fetch(`${BASE}/api/tracking/update`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ entity, trip, done: true }),
      }).catch(() => undefined);
  };

  return (
    <div className={className}>
      {on ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">Sharing your location · {sent} sent</span>
          <button type="button" className="rounded-md border px-3 py-1.5 text-sm" onClick={() => stop(false)}>Pause</button>
          <button type="button" className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground" onClick={() => stop(true)}>End trip</button>
        </div>
      ) : (
        <button type="button" className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground" onClick={() => setOn(true)}>
          Start sharing my location
        </button>
      )}
      {error && <p className="mt-2 text-sm text-destructive" role="alert">{error}</p>}
    </div>
  );
}
