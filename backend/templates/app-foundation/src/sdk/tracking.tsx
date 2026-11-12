"use client";

/**
 * Live tracking — a moving dot on a map, and the phone that moves it.
 *
 *   <LiveTrackingMap entity="Order" trip={order.id} pickup={restaurant} dropoff={home} />
 *       the customer's map: the driver's dot moves by itself as notes arrive
 *   <ShareLocation entity="Order" trip={order.id} />
 *       the driver's button: while on, this device sends where it is
 *   <FleetMap entity="Driver" onSelect={(id) => open(id)} />
 *       the admin's map: every driver on duty, moving, by vehicle type
 *   <FleetBeacon entity="Driver" trip={me.driverId} />
 *       shown while a driver is online: shares their own spot by itself (the
 *       "Go online" button is the page's workflow, not a second control)
 *
 * A FLEET is many people on the move at once (drivers online, no job yet). Each
 * is their own record; the app's read rules decide whom a viewer sees. A driver
 * who is not cleared to work, or is offline, cannot appear on the map.
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
import { formatDistance, type GeoPoint } from "./geo";
import { MapView, type MapPoint } from "./map";
import { minutesText, routeSource, useRoute } from "./route";

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
  const going = heading ?? (live.position?.stage === "to_dropoff" ? "dropoff" : "pickup");
  const target = going === "dropoff" ? dropoff : pickup;
  // THE ROAD AND THE TIME: from where the driver is to where they are heading, kept up to date as they move.
  const nav = useRoute(live.position, target);

  const points = React.useMemo<MapPoint[]>(() => {
    const out: MapPoint[] = [];
    // Both ends are always on the map; the one being driven to is the accent, the other is quiet.
    if (pickup) out.push({ id: "pickup", lat: pickup.lat, lng: pickup.lng, label: "Pickup", tone: going === "pickup" ? "accent" : "muted" });
    if (dropoff) out.push({ id: "dropoff", lat: dropoff.lat, lng: dropoff.lng, label: "Drop-off", tone: going === "dropoff" ? "accent" : "muted" });
    if (live.position)
      out.push({ id: "driver", lat: live.position.lat, lng: live.position.lng, label: live.stale ? "Driver (signal lost)" : "Driver", tone: live.stale ? "muted" : "primary" });
    return out;
  }, [pickup?.lat, pickup?.lng, dropoff?.lat, dropoff?.lng, going, live.position?.lat, live.position?.lng, live.stale]);

  const message =
    live.state === "denied" ? "This trip is not available to you."
    : live.state === "ended" ? "The trip has ended."
    : live.state === "reconnecting" ? "Reconnecting…"
    : !live.position ? "Waiting for the driver to share their location…"
    : live.stale ? "No signal from the driver for a while — showing the last known spot."
    : null;

  return (
    <div className={className}>
      <MapView points={points} route={nav.route?.path} keepInView height={height} />
      {message && <p className="mt-2 text-sm text-muted-foreground" role="status">{message}</p>}
      {!message && nav.route && nav.remainingKm !== null && nav.etaMin !== null && (
        <div className="mt-2 text-sm" role="status" aria-live="polite" data-route-summary="">
          <p className="font-medium text-foreground">
            {going === "pickup" ? "To pickup" : "To drop-off"}: {formatDistance(nav.remainingKm)} · {minutesText(nav.etaMin)}
            {nav.arriveAt ? ` · arrives ${nav.arriveAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
            {nav.offRoute ? " · finding a new route…" : ""}
          </p>
          <p className="text-muted-foreground" title={nav.route.notice}>{routeSource(nav.route)}{nav.route.notice && nav.route.provider !== "google" ? ` — ${nav.route.notice}` : ""}</p>
        </div>
      )}
    </div>
  );
}

const HOW_OFTEN_MS = 4_000;
/** While notes wait to go out, try again this often. */
const RETRY_MS = 5_000;
/** A driver who has not moved says "still here" this often (a line quiet for 30 s reads as lost). */
const STILL_HERE_MS = 20_000;

/** The driver's side. While `on`, this device posts its position every few seconds. */
export function useShareLocation(entity: string, trip: string | null | undefined, on: boolean, stage?: string, fleet?: boolean) {
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
        if (res.status === 409) {
          const why = (await res.json().catch(() => null)) as { error?: string } | null;
          throw new Error(why?.error || "This job is over.");
        }
        if (!res.ok && res.status >= 500) return; // server trouble: keep it, try again later
        queue.shift();
        setSent((n) => n + 1);
      }
      } finally {
        flushing = false;
      }
    };
    const run = () =>
      flush().then(() => setError(null), (e) => setError(e instanceof Error ? e.message : "Could not send."))
        .catch(() => setError("Could not send your location — trying again."));
    // A STILL DRIVER, AND A LINE THAT CAME BACK. Notes that failed to go out were only retried when a NEW reading
    // arrived, and a phone that is not moving gives none: after a dropped connection nothing was sent again, and
    // the driver left the map after two minutes of silence. So: retry while notes wait, retry the moment the browser
    // says it is online, and say "still here" now and then with the last known spot.
    let lastNote: Record<string, unknown> | null = null;
    const beat = window.setInterval(() => {
      if (queue.length) { void run(); return; }
      if (lastNote && Date.now() - lastSent > STILL_HERE_MS) {
        lastSent = Date.now();
        queue.push({ ...lastNote, at: lastSent });
        void run();
      }
    }, RETRY_MS);
    const backOnline = () => { if (queue.length) void run(); };
    window.addEventListener("online", backOnline);
    const id = navigator.geolocation.watchPosition(
      (pos) => {
        const at = Date.now();
        if (at - lastSent < HOW_OFTEN_MS) return;
        lastSent = at;
        const note = {
          entity, trip, ...(fleet ? { fleet: true } : {}), lat: pos.coords.latitude, lng: pos.coords.longitude, at,
          heading: pos.coords.heading ?? undefined, speed: pos.coords.speed ?? undefined,
          accuracy: pos.coords.accuracy, stage: stageRef.current,
        };
        lastNote = note;
        queue.push(note);
        if (queue.length > 50) queue = queue.slice(-50); // a long outage keeps the latest only
        void run();
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
      window.clearInterval(beat);
      window.removeEventListener("online", backOnline);
    };
  }, [entity, trip, on, fleet]);

  return { error, sent };
}

/** One button: start or stop sharing for a trip. Ending the trip tells the customer. */
export function ShareLocation({ entity, trip, stage, fleet, className }: { entity: string; trip: string; stage?: string; fleet?: boolean; className?: string }) {
  const [on, setOn] = React.useState(false);
  const { error, sent } = useShareLocation(entity, trip, on, stage, fleet);

  const stop = async (finish: boolean) => {
    setOn(false);
    if (finish)
      await fetch(`${BASE}/api/tracking/update`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ entity, trip, done: true, ...(fleet ? { fleet: true } : {}) }),
      }).catch(() => undefined);
  };

  return (
    <div className={className}>
      {on ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">{fleet ? "You are online" : "Sharing your location"} · {sent} sent</span>
          {!fleet && <button type="button" className="rounded-md border px-3 py-1.5 text-sm" onClick={() => stop(false)}>Pause</button>}
          <button type="button" className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground" onClick={() => stop(true)}>{fleet ? "Go offline" : "End trip"}</button>
        </div>
      ) : (
        <button type="button" className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground" onClick={() => setOn(true)}>
          {fleet ? "Go online" : "Start sharing my location"}
        </button>
      )}
      {error && <p className="mt-2 text-sm text-destructive" role="alert">{error}</p>}
    </div>
  );
}

/**
 * A DRIVER'S POSITION, SHARED WITHOUT A SECOND BUTTON. "Go online" is the
 * workflow a page already has: it moves the driver's status. This sits on the
 * screen while that status is online and sends the phone's position by itself,
 * and stops when it unmounts (they went offline). With `ShareLocation fleet`
 * beside the workflow button a driver saw two "Go online" controls and had to
 * press both.
 */
export function FleetBeacon({ entity, trip, on = true, className }: { entity: string; trip: string; on?: boolean; className?: string }) {
  const { error, sent } = useShareLocation(entity, trip, on, undefined, true);
  return (
    <div className={className} role="status" aria-live="polite">
      {error ? (
        <p className="text-sm text-destructive" role="alert">{error}</p>
      ) : (
        <p className="text-sm text-muted-foreground">
          {sent > 0 ? `Sharing your position · ${sent} sent` : "Finding your position… allow location for this site if your browser asks."}
        </p>
      )}
    </div>
  );
}

/* ------------------------------ THE FLEET ------------------------------- */

export type FleetMember = LivePosition & { id: string; label?: string; kind?: string };
const QUIET_MS = 60_000;

/** Everyone on duty that this person may see. Updates as they move. */
export function useFleet(entity: string): { members: FleetMember[]; state: "connecting" | "live" | "reconnecting" | "denied" } {
  const [byId, setById] = React.useState<Record<string, FleetMember>>({});
  const [state, setState] = React.useState<"connecting" | "live" | "reconnecting" | "denied">("connecting");

  React.useEffect(() => {
    setById({});
    setState("connecting");
    const line = new EventSource(`${BASE}/api/tracking/fleet?entity=${encodeURIComponent(entity)}`);
    let opened = false;
    line.onopen = () => { opened = true; setState("live"); };
    line.onerror = () => {
      if (!opened) { setState("denied"); line.close(); return; }
      setState("reconnecting");
    };
    line.onmessage = (e) => {
      try {
        const f = JSON.parse(e.data);
        setState("live");
        if (typeof f.gone === "string") {
          setById((old) => { const { [f.gone]: _gone, ...rest } = old; return rest; });
        } else if (typeof f.id === "string") {
          setById((old) => (old[f.id] && f.at <= old[f.id].at ? old : { ...old, [f.id]: f }));
        }
      } catch { /* a garbled frame is skipped */ }
    };
    return () => line.close();
  }, [entity]);

  return { members: React.useMemo(() => Object.values(byId), [byId]), state };
}

const TONES: MapPoint["tone"][] = ["primary", "accent", "danger"];
/** The same kind always gets the same colour: Bike, Auto, Sedan, SUV read apart at a glance. */
function toneFor(kind: string | undefined, kinds: string[]): MapPoint["tone"] {
  if (!kind) return "primary";
  const i = kinds.indexOf(kind);
  return TONES[(i < 0 ? 0 : i) % TONES.length];
}

export type FleetMapProps = {
  /** The kind of record the people on the move are: "Driver", "Courier". */
  entity: string;
  /** Show only these kinds ("Bike", "Sedan"); all when omitted. */
  kinds?: string[];
  /** Called with the record id when a pin is clicked: open that person's page. */
  onSelect?: (id: string) => void;
  /** Keep this person in view as they move. */
  follow?: string | null;
  height?: number | string;
  className?: string;
};

export function FleetMap({ entity, kinds, onSelect, follow, height = 480, className }: FleetMapProps) {
  const { members, state } = useFleet(entity);
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(t);
  }, []);

  const shown = members.filter((m) => !kinds?.length || (m.kind && kinds.includes(m.kind)));
  const allKinds = React.useMemo(() => [...new Set(members.map((m) => m.kind).filter((k): k is string => !!k))].sort(), [members]);
  const points = React.useMemo<MapPoint[]>(() => {
    const only = follow ? shown.filter((m) => m.id === follow) : shown;
    return only.map((m) => {
      const quiet = now - m.at > QUIET_MS;
      return {
        id: m.id, lat: m.lat, lng: m.lng,
        label: [m.label ?? "Driver", m.kind, quiet ? "signal lost" : undefined].filter(Boolean).join(" · "),
        tone: quiet ? "muted" : toneFor(m.kind, allKinds),
      };
    });
  }, [shown.map((m) => `${m.id}:${m.lat}:${m.lng}`).join("|"), follow, now, allKinds.join("|")]);

  const message =
    state === "denied" ? "You can't see this map."
    : state === "reconnecting" ? "Reconnecting…"
    : state === "connecting" ? "Connecting…"
    : !shown.length ? (members.length ? "No driver in this filter is sharing a position right now." : "No online driver is sharing a position right now.")
    : null;

  return (
    <div className={className}>
      {/* NO PINS: a zoomed-out world, not a street-level view of nowhere (a blank beige box looked broken). */}
      <MapView points={points} keepInView={!!follow} onPointClick={onSelect} height={height}
        center={points.length ? undefined : { lat: 20, lng: 10 }} zoom={points.length ? undefined : 1.6} />
      <p className="mt-2 text-sm text-muted-foreground" role="status">
        {message ?? `${shown.length} online`}
        {allKinds.length > 1 && !message ? ` · ${allKinds.join(", ")}` : ""}
      </p>
    </div>
  );
}
