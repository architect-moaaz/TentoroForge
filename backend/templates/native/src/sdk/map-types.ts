// The app SDK (native) — what a map is told and what it can be asked to do. PURE (no react-native import): the phone's
// map (`map.tsx`, react-native-maps) and the web picture's stand-in (`map.web.tsx`) both read these, so a screen is
// written once.

import type { GeoPoint } from "./geo";

export type MapPoint = GeoPoint & {
  id: string;
  label?: string;
  /** Which of the app's colours the pin takes. */
  tone?: "primary" | "accent" | "muted" | "danger";
  /** Degrees clockwise from north: a moving person's pin turns to face the way they go. */
  heading?: number;
};

export type MapViewProps = {
  points?: MapPoint[];
  /** A path through these places, in order — a trip, a route. */
  route?: GeoPoint[];
  center?: GeoPoint;
  /** Frame once, then only move the view when a pin leaves it. */
  keepInView?: boolean;
  onPointClick?: (id: string) => void;
  /** A number of points, or `"fill"` to take all the room there is (a map that IS the screen). */
  height?: number | "fill";
  /** Draw the phone's own blue dot for where the person is. */
  showsUser?: boolean;
  /** Keep the camera on this place as it moves (a driver on the way); the map stops following when the person drags it. */
  follow?: (GeoPoint & { heading?: number }) | null;
  /** Room taken by what floats over the map (a panel on top, a sheet below): the camera frames and centres inside the rest. */
  insets?: { top?: number; bottom?: number };
  /** The person moved the map with a finger. */
  onUserPan?: () => void;
  style?: unknown;
};

/** What a screen can ask of a map it holds a ref to. */
export type MapHandle = {
  /** Bring the camera back to `point` (or to what `follow` names), and follow again. */
  recenter: (point?: GeoPoint) => void;
  /** Frame every point and the route. */
  fit: () => void;
};

/** Is this CSS colour a dark one (`#rrggbb`, `rgb(...)`, `hsl(...)`)? A map is drawn dark under a dark design. Unreadable: not dark. */
export function isDarkColour(css: string | null | undefined): boolean {
  const s = String(css ?? "").trim().toLowerCase();
  let r: number, g: number, b: number;
  let m = s.match(/^#([0-9a-f]{6})$/) ?? s.match(/^#([0-9a-f]{3})$/);
  if (m) {
    const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
    [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  } else if ((m = s.match(/^rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)/))) {
    [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])];
  } else if ((m = s.match(/^hsla?\(\s*([\d.]+)(?:deg)?[ ,]+([\d.]+)%[ ,]+([\d.]+)%/))) {
    const h = Number(m[1]) / 360, sat = Number(m[2]) / 100, l = Number(m[3]) / 100;
    const q = l < 0.5 ? l * (1 + sat) : l + sat - l * sat, p = 2 * l - q;
    const f = (t: number) => { const x = ((t % 1) + 1) % 1; return x < 1 / 6 ? p + (q - p) * 6 * x : x < 1 / 2 ? q : x < 2 / 3 ? p + (q - p) * (2 / 3 - x) * 6 : p; };
    [r, g, b] = [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
  } else return false;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.4;
}
