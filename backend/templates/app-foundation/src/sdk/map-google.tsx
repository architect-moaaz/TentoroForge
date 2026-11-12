"use client";

/**
 * The same map, drawn by Google Maps. Used only when the app has a browser key
 * (NEXT_PUBLIC_GOOGLE_MAPS_API_KEY); `MapView` in ./map falls back to the free
 * map the moment Google refuses (a wrong or restricted key, billing off, the
 * Maps JavaScript API not enabled) or cannot be loaded, so a page never shows a
 * dead grey box.
 *
 * Loaded in the browser only, by a script tag on first use.
 */
import * as React from "react";
import { colour, middle, toHex, type MapViewProps } from "./map-shared";

type Gm = any; // the Google Maps namespace has no types in this app; its shape is stable and small here

let loading: Promise<Gm> | null = null;

function loadGoogle(key: string): Promise<Gm> {
  const w = window as unknown as { google?: Gm; gm_authFailure?: () => void; __forgeGmReady?: () => void };
  if (w.google?.maps?.importLibrary) return Promise.resolve(w.google.maps);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    w.gm_authFailure = () => window.dispatchEvent(new Event("forge-google-refused"));
    w.__forgeGmReady = () => resolve((window as unknown as { google: Gm }).google.maps);
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&loading=async&callback=__forgeGmReady`;
    s.async = true;
    s.onerror = () => { loading = null; reject(new Error("The Google Maps script could not be loaded.")); };
    document.head.appendChild(s);
  });
  return loading;
}

const PIN = "M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z";

export function GoogleMapView({
  points = [], route = [], center, zoom = 12, fit, keepInView, onPointClick, height = 320, className, apiKey, onFail,
}: MapViewProps & { apiKey: string; onFail: () => void }) {
  const box = React.useRef<HTMLDivElement | null>(null);
  const gm = React.useRef<Gm>(null);
  const map = React.useRef<Gm>(null);
  const pins = React.useRef<Gm[]>([]);
  const line = React.useRef<Gm>(null);
  const info = React.useRef<Gm>(null);
  const framed = React.useRef(false);
  const [ready, setReady] = React.useState(false);
  const clicked = React.useRef(onPointClick);
  clicked.current = onPointClick;
  const failed = React.useRef(onFail);
  failed.current = onFail;

  // The map itself, once.
  React.useEffect(() => {
    let gone = false;
    const refused = () => { if (!gone) failed.current(); };
    window.addEventListener("forge-google-refused", refused);
    (async () => {
      try {
        const maps = await loadGoogle(apiKey);
        const { Map: GMap, InfoWindow } = await maps.importLibrary("maps");
        await maps.importLibrary("marker");
        if (gone || !box.current) return;
        gm.current = maps;
        const at = center ?? middle([...points, ...route]);
        map.current = new GMap(box.current, {
          center: { lat: at.lat, lng: at.lng }, zoom,
          disableDefaultUI: true, zoomControl: true, gestureHandling: "cooperative", clickableIcons: false,
        });
        info.current = new InfoWindow();
        setReady(true);
      } catch {
        refused();
      }
    })();
    return () => {
      gone = true;
      window.removeEventListener("forge-google-refused", refused);
      for (const p of pins.current) p.setMap(null);
      line.current?.setMap(null);
      pins.current = [];
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The pins and the path, whenever they change.
  React.useEffect(() => {
    const maps = gm.current;
    const m = map.current;
    if (!maps || !m || !ready) return;
    for (const p of pins.current) p.setMap(null);
    pins.current = points.map((p) => {
      const pin = new maps.Marker({
        position: { lat: p.lat, lng: p.lng }, map: m, title: p.label,
        icon: { path: PIN, fillColor: toHex(colour(p.tone)), fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 1.5, scale: 1.7, anchor: new maps.Point(12, 22) },
      });
      pin.addListener("click", () => {
        if (p.label) { info.current?.setContent(document.createTextNode(p.label)); info.current?.open({ map: m, anchor: pin }); }
        clicked.current?.(p.id);
      });
      return pin;
    });
    const path = route.map((p) => ({ lat: p.lat, lng: p.lng }));
    if (path.length > 1) {
      if (!line.current) {
        line.current = new maps.Polyline({ map: m, path, strokeColor: toHex(colour("accent")), strokeOpacity: 0.9, strokeWeight: 5 });
      } else {
        line.current.setMap(m);
        line.current.setPath(path);
      }
    } else line.current?.setMap(null);

    const all = [...points, ...route];
    const bounds = () => {
      const b = new maps.LatLngBounds();
      for (const p of all) b.extend({ lat: p.lat, lng: p.lng });
      return b;
    };
    if (keepInView && all.length > 1) {
      const view = m.getBounds();
      if (!framed.current || !view || all.some((p) => !view.contains({ lat: p.lat, lng: p.lng }))) {
        m.fitBounds(bounds(), 64);
        framed.current = true;
      }
    } else if ((fit ?? all.length > 1) && all.length > 1) {
      m.fitBounds(bounds(), 48);
    } else if (all.length === 1) {
      m.setCenter({ lat: all[0].lat, lng: all[0].lng });
      if ((m.getZoom() ?? 12) < 5) m.setZoom(12); // from the zoomed-out empty view to the first pin: come in close
    }
  }, [points, route, fit, keepInView, ready]);

  return (
    <div ref={box} className={"relative overflow-hidden rounded-xl border bg-muted " + (className ?? "")} style={{ height }} aria-label="Map" data-map="google" data-pins={points.length} />
  );
}
