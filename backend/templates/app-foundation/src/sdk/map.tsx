"use client";

/**
 * A map: places as pins, a path as a line — a rider on the way, restaurants
 * near you, a delivery zone's outlets. MapLibre over OpenFreeMap's tiles (no
 * key); `NEXT_PUBLIC_MAP_STYLE` names another style.
 *
 * LOADED IN THE BROWSER ONLY. A map library reaches for `window` the moment it
 * is imported, and a page's code is rendered on the server first: imported at
 * the top, it would crash every page that shows a map. It is fetched inside an
 * effect, so the server renders the empty frame and the browser fills it.
 *
 *   <MapView points={[{ id: o.id, lat: o.lat, lng: o.lng, label: o.name }]}
 *            route={trip.path} onPointClick={(id) => open(id)} />
 */
import * as React from "react";
import type { GeoPoint } from "./geo";
import "maplibre-gl/dist/maplibre-gl.css";

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
  onPointClick?: (id: string) => void;
  height?: number | string;
  className?: string;
};

const DEFAULT_STYLE = "https://tiles.openfreemap.org/styles/liberty";

const TONE_VAR: Record<NonNullable<MapPoint["tone"]>, string> = {
  primary: "--primary", accent: "--accent", muted: "--muted-foreground", danger: "--destructive",
};

function colour(tone: MapPoint["tone"]): string {
  if (typeof window === "undefined") return "#2563eb";
  const v = getComputedStyle(document.documentElement).getPropertyValue(TONE_VAR[tone ?? "primary"]).trim();
  return v ? `hsl(${v})` : "#2563eb";
}

function middle(points: GeoPoint[]): GeoPoint {
  if (!points.length) return { lat: 20, lng: 0 };
  return {
    lat: points.reduce((s, p) => s + p.lat, 0) / points.length,
    lng: points.reduce((s, p) => s + p.lng, 0) / points.length,
  };
}

type Lib = typeof import("maplibre-gl");

export function MapView({
  points = [], route = [], center, zoom = 12, fit, onPointClick, height = 320, className,
}: MapViewProps) {
  const box = React.useRef<HTMLDivElement | null>(null);
  const map = React.useRef<import("maplibre-gl").Map | null>(null);
  const lib = React.useRef<Lib | null>(null);
  const pins = React.useRef<import("maplibre-gl").Marker[]>([]);
  const [ready, setReady] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const clicked = React.useRef(onPointClick);
  clicked.current = onPointClick;

  // The map itself, once.
  React.useEffect(() => {
    let gone = false;
    (async () => {
      try {
        const m = (await import("maplibre-gl")) as unknown as Lib & { default?: Lib };
        const maplibre = (m.default ?? m) as Lib;
        if (gone || !box.current) return;
        lib.current = maplibre;
        const at = center ?? middle([...points, ...route]);
        const instance = new maplibre.Map({
          container: box.current,
          style: process.env.NEXT_PUBLIC_MAP_STYLE || DEFAULT_STYLE,
          center: [at.lng, at.lat],
          zoom,
          attributionControl: { compact: true },
        });
        instance.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
        instance.on("load", () => { if (!gone) setReady(true); });
        map.current = instance;
      } catch {
        if (!gone) setFailed(true);
      }
    })();
    return () => {
      gone = true;
      map.current?.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The pins and the path, whenever they change.
  React.useEffect(() => {
    const m = map.current;
    const maplibre = lib.current;
    if (!m || !maplibre || !ready) return;
    for (const pin of pins.current) pin.remove();
    pins.current = points.map((p) => {
      const pin = new maplibre.Marker({ color: colour(p.tone) }).setLngLat([p.lng, p.lat]);
      if (p.label) pin.setPopup(new maplibre.Popup({ offset: 24, closeButton: false }).setText(p.label));
      pin.getElement().addEventListener("click", () => clicked.current?.(p.id));
      return pin.addTo(m);
    });
    const line = {
      type: "Feature" as const, properties: {},
      geometry: { type: "LineString" as const, coordinates: route.map((p) => [p.lng, p.lat]) },
    };
    const source = m.getSource("forge-route") as import("maplibre-gl").GeoJSONSource | undefined;
    if (source) source.setData(line);
    else if (route.length > 1) {
      m.addSource("forge-route", { type: "geojson", data: line });
      m.addLayer({ id: "forge-route", type: "line", source: "forge-route",
                   paint: { "line-color": colour("accent"), "line-width": 4, "line-opacity": 0.85 } });
    }
    const all = [...points, ...route];
    if ((fit ?? all.length > 1) && all.length > 1) {
      const bounds = new maplibre.LngLatBounds();
      for (const p of all) bounds.extend([p.lng, p.lat]);
      m.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 });
    } else if (all.length === 1) {
      m.setCenter([all[0].lng, all[0].lat]);
    }
  }, [points, route, fit, ready]);

  return (
    <div
      ref={box}
      className={"relative overflow-hidden rounded-xl border bg-muted " + (className ?? "")}
      style={{ height }}
      aria-label="Map"
    >
      {failed && (
        <p className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-muted-foreground">
          The map could not be loaded.
        </p>
      )}
    </div>
  );
}
