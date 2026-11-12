// The app SDK (native) — live tracking on the phone: the driver's side and the watcher's side. The same names and
// the same rules as the web's `@/sdk/tracking`, over HTTP (the phone cannot hold the web's open line, so the watcher
// asks for the newest note every few seconds).
//
//   DRIVER      <FleetBeacon entity="Driver" trip={driver.id} />        while they are online: shares by itself
//               <ShareLocation entity="Ride" trip={ride.id} stage={…} />  a Start / End button for one trip
//   WATCHER     <LiveTrackingMap entity="Ride" trip={ride.id} pickup={…} dropoff={…} />
//                  both ends, the driver, the road, the distance left and the arrival time
//
// WHILE THE APP IS OPEN. Position is shared while the app is in front of the person. Sharing with the screen off
// needs background location, which is its own permission and needs a real build (not Expo Go): not part of this.

import * as React from "react";
import { AppState, StyleSheet, View } from "react-native";
import * as Location from "expo-location";
import { apiJson } from "./api";
import { formatDistance, type GeoPoint } from "./geo";
import { MapView, type MapPoint } from "./map";
import { minutesText, routeSource, useRoute } from "./route";
import { ensureForegroundLocation } from "./permission";
import { createSender, RETRY_MS } from "./tracking-core";
import { Button } from "../ui/Button";
import { Text } from "../ui/Text";

const POLL_MS = 4_000;
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

/** Follow one trip: asks for the newest note every few seconds. Stops when the trip ends. */
export function useLiveTrip(entity: string, trip: string | null | undefined): LiveTrip {
  const [position, setPosition] = React.useState<LivePosition | null>(null);
  const [state, setState] = React.useState<LiveTrip["state"]>("connecting");
  const [now, setNow] = React.useState(() => Date.now());

  React.useEffect(() => {
    if (!trip) return;
    setPosition(null);
    setState("connecting");
    let gone = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const path = `/api/tracking/stream?entity=${encodeURIComponent(entity)}&trip=${encodeURIComponent(trip)}&snapshot=1`;
    const poll = async () => {
      const res = await apiJson<{ position: LivePosition | null; done: boolean }>(path);
      if (gone) return;
      if (res.networkError || res.status >= 500) {
        setState((s) => (s === "connecting" ? s : "reconnecting"));
      } else if (res.status === 401 || res.status === 403 || res.status === 404) {
        setState("denied");
        return;
      } else if (res.body?.done) {
        setState("ended");
        return;
      } else {
        setState("live");
        const p = res.body?.position;
        // An older note never replaces a newer one.
        if (p) setPosition((old) => (old && p.at <= old.at ? old : p));
      }
      timer = setTimeout(poll, POLL_MS);
    };
    void poll();
    const tick = setInterval(() => setNow(Date.now()), 5_000);
    return () => { gone = true; if (timer) clearTimeout(timer); clearInterval(tick); };
  }, [entity, trip]);

  return { position, state, stale: !!position && now - position.at > STALE_MS };
}

/** The driver's side. While `on`, this phone sends its position every few seconds, retries when the line was lost,
 *  and says "still here" when it stands still. */
export function useShareLocation(entity: string, trip: string | null | undefined, on: boolean, stage?: string, fleet?: boolean) {
  const [error, setError] = React.useState<string | null>(null);
  const [sent, setSent] = React.useState(0);
  const stageRef = React.useRef(stage);
  stageRef.current = stage;

  React.useEffect(() => {
    if (!trip || !on) return;
    let gone = false;
    let watch: Location.LocationSubscription | null = null;
    setError(null);
    const sender = createSender({
      now: () => Date.now(),
      post: async (note) => {
        const res = await apiJson<{ error?: string }>("/api/tracking/update", { method: "POST", body: note });
        return { status: res.networkError ? 0 : res.status, error: res.body?.error };
      },
      onSent: () => { if (!gone) setSent((n) => n + 1); },
      onError: (message) => { if (!gone) setError(message); },
    });
    (async () => {
      if (!(await ensureForegroundLocation())) {
        if (!gone) setError("Location is blocked — allow it for this app in Settings.");
        return;
      }
      const sub = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.High, timeInterval: 2_000, distanceInterval: 5 },
        (pos) => {
          const c = pos.coords;
          sender.reading({
            entity, trip, ...(fleet ? { fleet: true } : {}), lat: c.latitude, lng: c.longitude, at: Date.now(),
            heading: c.heading != null && c.heading >= 0 ? c.heading : undefined,
            speed: c.speed != null && c.speed >= 0 ? c.speed : undefined,
            accuracy: c.accuracy ?? undefined, stage: stageRef.current,
          });
        },
      );
      if (gone) sub.remove(); else watch = sub;
    })().catch(() => {
      if (!gone) setError("Your location could not be found — move to open sky or check GPS.");
    });
    const timer = setInterval(() => { void sender.tick(); }, RETRY_MS);
    const app = AppState.addEventListener("change", (s) => { if (s === "active") void sender.online(); });
    return () => { gone = true; watch?.remove(); clearInterval(timer); app.remove(); };
  }, [entity, trip, on, fleet]);

  return { error, sent };
}

/** One button: start or stop sharing for a trip. */
export function ShareLocation({ entity, trip, stage, fleet }: { entity: string; trip: string; stage?: string; fleet?: boolean }) {
  const [on, setOn] = React.useState(false);
  const { error, sent } = useShareLocation(entity, trip, on, stage, fleet);
  return (
    <View style={styles.row} accessibilityRole="summary">
      {error ? <Text tone="danger" variant="caption">{error}</Text> : on ? <Text variant="caption" tone="muted">Sharing your location · {sent} sent</Text> : null}
      <Button variant={on ? "outline" : "primary"} onPress={() => setOn((v) => !v)}>
        {on ? (fleet ? "Go offline" : "End trip") : (fleet ? "Go online" : "Start sharing my location")}
      </Button>
    </View>
  );
}

/** A driver's position, shared without a second button: while this is on screen the position is sent. */
export function FleetBeacon({ entity, trip, on = true }: { entity: string; trip: string; on?: boolean }) {
  const { error, sent } = useShareLocation(entity, trip, on, undefined, true);
  return (
    <View accessibilityRole="summary" accessibilityLiveRegion="polite">
      {error ? (
        <Text tone="danger" variant="caption">{error}</Text>
      ) : (
        <Text variant="caption" tone="muted">
          {sent > 0 ? `Sharing your position · ${sent} sent` : "Finding your position… allow location if the phone asks."}
        </Text>
      )}
    </View>
  );
}

export type LiveTrackingMapProps = {
  entity: string;
  trip: string;
  pickup?: GeoPoint | null;
  dropoff?: GeoPoint | null;
  /** Which end the driver is heading to; read from the trip's stage when omitted. */
  heading?: "pickup" | "dropoff";
  height?: number;
};

/** The driver on the map with both ends, the road between them, the distance left and the arrival time. */
export function LiveTrackingMap({ entity, trip, pickup, dropoff, heading, height = 320 }: LiveTrackingMapProps) {
  const live = useLiveTrip(entity, trip);
  const going = heading ?? (live.position?.stage === "to_dropoff" ? "dropoff" : "pickup");
  const target = going === "dropoff" ? dropoff : pickup;
  const nav = useRoute(live.position, target);

  const points = React.useMemo<MapPoint[]>(() => {
    const out: MapPoint[] = [];
    if (pickup) out.push({ id: "pickup", lat: pickup.lat, lng: pickup.lng, label: "Pickup", tone: going === "pickup" ? "accent" : "muted" });
    if (dropoff) out.push({ id: "dropoff", lat: dropoff.lat, lng: dropoff.lng, label: "Drop-off", tone: going === "dropoff" ? "accent" : "muted" });
    if (live.position) out.push({ id: "driver", lat: live.position.lat, lng: live.position.lng, label: live.stale ? "Driver (signal lost)" : "Driver", tone: live.stale ? "muted" : "primary" });
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
    <View>
      <MapView points={points} route={nav.route?.path} keepInView height={height} />
      {message ? (
        <Text variant="caption" tone="muted" style={styles.note}>{message}</Text>
      ) : nav.route && nav.remainingKm !== null && nav.etaMin !== null ? (
        <View style={styles.note} accessibilityLiveRegion="polite">
          <Text variant="label">
            {going === "pickup" ? "To pickup" : "To drop-off"}: {formatDistance(nav.remainingKm)} · {minutesText(nav.etaMin)}
            {nav.arriveAt ? ` · arrives ${nav.arriveAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
            {nav.offRoute ? " · finding a new route…" : ""}
          </Text>
          <Text variant="caption" tone="muted">
            {routeSource(nav.route)}{nav.route.notice && nav.route.provider !== "google" ? ` — ${nav.route.notice}` : ""}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { gap: 8 },
  note: { marginTop: 8 },
});
