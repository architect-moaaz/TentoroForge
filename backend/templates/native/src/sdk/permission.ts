// The app SDK (native) — asking for the device's location while the app is open, without asking twice.
//
// Two screens that both ask at the same moment (the home screen that shares a position, the map that follows it) must not
// each put the question: the second asked while the first was still up and never got an answer, so its map waited for
// ever. So: look first. Already allowed: go. Never allowed and the person said "don't ask again": no. Otherwise ask, once at a
// time, and everyone waiting gets the same answer.

import * as Location from "expo-location";

let asking: Promise<boolean> | null = null;

/** True when this app may read the device's position while it is open. */
export async function ensureForegroundLocation(): Promise<boolean> {
  const have = await Location.getForegroundPermissionsAsync();
  if (have.granted) return true;
  if (!have.canAskAgain) return false;
  if (!asking) {
    asking = Location.requestForegroundPermissionsAsync()
      .then((answer) => answer.granted)
      .finally(() => { asking = null; });
  }
  return asking;
}
