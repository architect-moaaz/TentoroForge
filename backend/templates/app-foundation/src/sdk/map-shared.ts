// What both map engines (MapLibre, Google) share: the props a page passes, and a few helpers.
// Pure and safe to import anywhere.
import type { GeoPoint } from "./geo";

export type MapPoint = GeoPoint & {
  id: string;
  label?: string;
  /** Which of the app's colours the pin takes. */
  tone?: "primary" | "accent" | "muted" | "danger";
};

/** An area drawn on the map: a circle (centre and radius in metres) or a polygon (its corners). */
export type MapZone = {
  id: string;
  label?: string;
  tone?: "primary" | "accent" | "muted" | "danger";
  /** Drawn faint and dashed: a zone that is switched off. */
  inactive?: boolean;
} & (
  | { shape: "circle"; center: GeoPoint; radiusM: number }
  | { shape: "polygon"; ring: GeoPoint[] }
);

export type MapViewProps = {
  points?: MapPoint[];
  /** Areas drawn under the pins. */
  zones?: MapZone[];
  /** The map was clicked at this place (not a pin, not a zone's edge). */
  onMapClick?: (at: GeoPoint) => void;
  onZoneClick?: (id: string) => void;
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

/** A zone's outline as a closed ring of places: a circle becomes 64 corners, which no eye can tell from round. */
export function ringOf(z: MapZone, steps = 64): GeoPoint[] {
  if (z.shape === "polygon") return z.ring.length && (z.ring[0].lat !== z.ring[z.ring.length - 1].lat || z.ring[0].lng !== z.ring[z.ring.length - 1].lng) ? [...z.ring, z.ring[0]] : z.ring;
  const out: GeoPoint[] = [];
  const dLat = z.radiusM / 111_320;
  const dLng = z.radiusM / (111_320 * Math.max(0.01, Math.cos((z.center.lat * Math.PI) / 180)));
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    out.push({ lat: z.center.lat + dLat * Math.sin(a), lng: z.center.lng + dLng * Math.cos(a) });
  }
  return out;
}

export function middle(points: GeoPoint[]): GeoPoint {
  if (!points.length) return { lat: 20, lng: 0 };
  return {
    lat: points.reduce((s, p) => s + p.lat, 0) / points.length,
    lng: points.reduce((s, p) => s + p.lng, 0) / points.length,
  };
}
