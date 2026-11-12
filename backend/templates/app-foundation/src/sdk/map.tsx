"use client";

/**
 * A map: places as pins, a path as a line — a rider on the way, restaurants
 * near you, a delivery zone's outlets.
 *
 * TWO ENGINES, ONE COMPONENT. By default MapLibre over OpenFreeMap's tiles: no
 * key, no billing. When the app has a Google Maps browser key
 * (NEXT_PUBLIC_GOOGLE_MAPS_API_KEY) the same map is drawn by Google Maps;
 * NEXT_PUBLIC_MAP_PROVIDER=openfreemap keeps the free one even then. If Google
 * refuses (wrong or restricted key, billing off, the API not enabled) the free
 * map takes over by itself. `NEXT_PUBLIC_MAP_STYLE` names another MapLibre style.
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
import "maplibre-gl/dist/maplibre-gl.css";
import { GoogleMapView } from "./map-google";
import { colour, middle, type MapPoint, type MapViewProps } from "./map-shared";

export type { MapPoint, MapViewProps } from "./map-shared";

const DEFAULT_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const GOOGLE_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || "";
const WANT_GOOGLE = !!GOOGLE_KEY && (process.env.NEXT_PUBLIC_MAP_PROVIDER ?? "google") !== "openfreemap";

type Lib = typeof import("maplibre-gl");

/** Which engine this build draws maps with: "google" or "openfreemap". */
export function mapProvider(): "google" | "openfreemap" {
  return WANT_GOOGLE ? "google" : "openfreemap";
}

export function MapView(props: MapViewProps) {
  const [googleFailed, setGoogleFailed] = React.useState(false);
  if (WANT_GOOGLE && !googleFailed) {
    return <GoogleMapView {...props} apiKey={GOOGLE_KEY} onFail={() => setGoogleFailed(true)} />;
  }
  return <MapLibreView {...props} />;
}

function MapLibreView({
  points = [], route = [], center, zoom = 12, fit, keepInView, onPointClick, height = 320, className,
}: MapViewProps) {
  const framed = React.useRef(false);
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
    if (keepInView && all.length > 1) {
      const view = m.getBounds();
      if (!framed.current || all.some((p) => !view.contains([p.lng, p.lat]))) {
        const bounds = new maplibre.LngLatBounds();
        for (const p of all) bounds.extend([p.lng, p.lat]);
        m.fitBounds(bounds, { padding: 64, maxZoom: 15, duration: framed.current ? 500 : 0 });
        framed.current = true;
      }
    } else if ((fit ?? all.length > 1) && all.length > 1) {
      const bounds = new maplibre.LngLatBounds();
      for (const p of all) bounds.extend([p.lng, p.lat]);
      m.fitBounds(bounds, { padding: 48, maxZoom: 15, duration: 0 });
    } else if (all.length === 1) {
      // from the zoomed-out empty view (below 5) to the first pin: come in close; otherwise keep the viewer's zoom
      m.jumpTo({ center: [all[0].lng, all[0].lat], zoom: m.getZoom() < 5 ? 12 : m.getZoom() });
    }
  }, [points, route, fit, keepInView, ready]);

  return (
    <div
      ref={box}
      className={"relative overflow-hidden rounded-xl border bg-muted " + (className ?? "")}
      style={{ height }}
      aria-label="Map"
      data-map="openfreemap"
      data-pins={points.length}
    >
      {failed && (
        <p className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-muted-foreground">
          The map could not be loaded.
        </p>
      )}
    </div>
  );
}
