// The app SDK (native) — where the person is, once, with their permission. The
// web's `askPosition` (behind its `location` form input and <NearMe />): the
// position is rounded to about 100 m (`roundPoint`), because a record says which
// neighbourhood, never which door. A screen shows a distance, not these numbers.

import * as Location from "expo-location";
import { roundPoint, type GeoPoint } from "./geo";

/** The approximate position, or throws a sentence: permission declined, or no fix. */
export async function askPosition(): Promise<GeoPoint> {
  const ask = await Location.requestForegroundPermissionsAsync();
  if (!ask.granted) throw new Error("Location permission was declined — allow it for this app in Settings to use this.");
  try {
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    return roundPoint({ lat: pos.coords.latitude, lng: pos.coords.longitude });
  } catch {
    throw new Error("Your location could not be found — try again.");
  }
}
