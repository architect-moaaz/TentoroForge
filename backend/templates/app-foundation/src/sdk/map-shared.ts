// What both map engines (MapLibre, Google) share: the props a page passes, and a few helpers.
// Pure and safe to import anywhere.
import type { GeoPoint } from "./geo";

export type MapPoint = GeoPoint & {
  id: string;
  label?: string;
  /** Which of the app's colours the pin takes. */
  tone?: "primary" | "accent" | "muted" | "danger";
};

export type MapViewProps = {
  points?: MapPoint[];
  /** A path through these places, in order — a trip, a route. */
  route?: GeoPoint[];
  /** Where it opens; the points' middle when omitted. */
  center?: GeoPoint;
  zoom?: number;
  /** Frame every point and the route (default true when there is more than one). */
  fit?: boolean;
  /** Frame once, then only move the view when a pin leaves it (a driver driving away). */
  keepInView?: boolean;
  onPointClick?: (id: string) => void;
  height?: number | string;
  className?: string;
};

const TONE_VAR: Record<NonNullable<MapPoint["tone"]>, string> = {
  primary: "--primary", accent: "--accent", muted: "--muted-foreground", danger: "--destructive",
};

/** The app's own colour for a pin, as CSS (`hsl(...)`). */
export function colour(tone: MapPoint["tone"]): string {
  if (typeof window === "undefined") return "#2563eb";
  const v = getComputedStyle(document.documentElement).getPropertyValue(TONE_VAR[tone ?? "primary"]).trim();
  return v ? `hsl(${v})` : "#2563eb";
}

/** Any CSS colour as #rrggbb, for engines that only take hex (Google's pin symbols). */
export function toHex(css: string): string {
  if (typeof document === "undefined") return "#2563eb";
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return "#2563eb";
  ctx.fillStyle = "#2563eb";
  ctx.fillStyle = css;
  const out = String(ctx.fillStyle);
  if (out.startsWith("#")) return out;
  const m = out.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  return m ? "#" + [m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, "0")).join("") : "#2563eb";
}

export function middle(points: GeoPoint[]): GeoPoint {
  if (!points.length) return { lat: 20, lng: 0 };
  return {
    lat: points.reduce((s, p) => s + p.lat, 0) / points.length,
    lng: points.reduce((s, p) => s + p.lng, 0) / points.length,
  };
}
