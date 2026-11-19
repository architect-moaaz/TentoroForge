// The app SDK (native) — where THIS device is, live, for a screen that draws it (the blue dot, the camera that follows).
// Not the same as sharing a position with the server (`useShareLocation` sends it): this only reads it.
//
//   const here = useDevicePosition();        // { position, state, stale, openSettings }
//   <MapScreen follow={here.position} … />
//
// States, in words a screen can show: "asking" (the permission question is up), "denied" (the person said no: say how
// to allow it), "unavailable" (no fix: indoors, GPS off), "ok". While the app is open in front of the person.

import * as React from "react";
import { Linking } from "react-native";
import * as Location from "expo-location";
import type { GeoPoint } from "./geo";
import { ensureForegroundLocation } from "./permission";

export type DevicePosition = GeoPoint & { heading?: number; speed?: number; accuracy?: number; at: number };
export type PositionState = "asking" | "denied" | "unavailable" | "ok";

/** A reading older than this is not "where they are now". */
export const STALE_AFTER_MS = 30_000;
/** With no fix at all after this long the screen says the location cannot be found. */
export const GIVE_UP_MS = 20_000;

export function useDevicePosition(on = true): {
  position: DevicePosition | null; state: PositionState; stale: boolean; openSettings: () => void;
} {
  const [position, setPosition] = React.useState<DevicePosition | null>(null);
  const [state, setState] = React.useState<PositionState>("asking");
  const [now, setNow] = React.useState(() => Date.now());

  React.useEffect(() => {
    if (!on) return;
    let gone = false;
    let watch: Location.LocationSubscription | null = null;
    setState("asking");
    (async () => {
      const allowed = await ensureForegroundLocation();
      if (gone) return;
      if (!allowed) { setState("denied"); return; }
      // The last known spot, so the map has somewhere to be while the first fix is found. NOT waited for: on some devices
      // that call never answers, and listening must not wait behind it.
      Location.getLastKnownPositionAsync()
        .then((last) => {
          if (last && !gone) {
            setPosition((old) => old ?? { lat: last.coords.latitude, lng: last.coords.longitude, at: last.timestamp });
            setState("ok");
          }
        })
        .catch(() => undefined);
      const sub = await Location.watchPositionAsync(
        // distanceInterval 0: a driver waiting at the kerb still reports at the interval, so a parked phone is not shown as stale
        { accuracy: Location.Accuracy.High, timeInterval: 2_000, distanceInterval: 0 },
        (pos) => {
          const c = pos.coords;
          setPosition({
            lat: c.latitude, lng: c.longitude, at: Date.now(),
            heading: c.heading != null && c.heading >= 0 ? c.heading : undefined,
            speed: c.speed != null && c.speed >= 0 ? c.speed : undefined,
            accuracy: c.accuracy ?? undefined,
          });
          setState("ok");
        },
      );
      if (gone) sub.remove(); else watch = sub;
    })().catch(() => { if (!gone) setState("unavailable"); });
    const tick = setInterval(() => setNow(Date.now()), 5_000);
    // No fix at all after a while: say so, in words, instead of "finding" for ever. A fix that comes later clears it.
    const giveUp = setTimeout(() => { if (!gone) setState((s) => (s === "asking" ? "unavailable" : s)); }, GIVE_UP_MS);
    return () => { gone = true; watch?.remove(); clearInterval(tick); clearTimeout(giveUp); };
  }, [on]);

  return {
    position, state,
    stale: !!position && now - position.at > STALE_AFTER_MS,
    openSettings: () => { void Linking.openSettings(); },
  };
}
