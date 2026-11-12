// The app SDK (native) — a map: places as pins, a path as a line, the same props as the web's `MapView`.
//
//   <MapView points={[{ id: "pickup", lat, lng, label: "Pickup" }]} route={path} keepInView height={320} />
//
// react-native-maps draws it: Apple Maps on iPhone, Google Maps on Android (an Android BUILD needs the Maps SDK for
// Android key in `app.json`: `android.config.googleMaps.apiKey`; Expo Go carries its own). A pin's colour is one of
// the app's own (`primary`, `accent`, `muted`, `danger`).
//
// `keepInView` frames everything once, then moves the view only when a pin leaves it (a driver driving away).

import * as React from "react";
import { StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import RNMap, { Marker, Polyline, type MapViewProps as RNMapProps, type Region } from "react-native-maps";
import { useTheme } from "../theme";
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
  center?: GeoPoint;
  /** Frame once, then only move the view when a pin leaves it. */
  keepInView?: boolean;
  onPointClick?: (id: string) => void;
  height?: number;
  style?: StyleProp<ViewStyle>;
};

const PADDING = { top: 64, right: 64, bottom: 64, left: 64 };

function inside(region: Region | null, p: GeoPoint): boolean {
  if (!region) return false;
  return Math.abs(p.lat - region.latitude) <= region.latitudeDelta / 2 && Math.abs(p.lng - region.longitude) <= region.longitudeDelta / 2;
}

export function MapView({ points = [], route = [], center, keepInView, onPointClick, height = 320, style }: MapViewProps) {
  const theme = useTheme();
  const ref = React.useRef<RNMap | null>(null);
  const region = React.useRef<Region | null>(null);
  const framed = React.useRef(false);
  const [ready, setReady] = React.useState(false);

  const all = React.useMemo<GeoPoint[]>(() => [...points, ...route], [points, route]);
  const tone = (t: MapPoint["tone"]) => theme.colors[t === "accent" ? "accent" : t === "muted" ? "mutedForeground" : t === "danger" ? "destructive" : "primary"];

  React.useEffect(() => {
    const map = ref.current;
    if (!map || !ready || all.length === 0) return;
    if (all.length === 1) {
      if (!framed.current || !inside(region.current, all[0])) {
        map.animateToRegion({ latitude: all[0].lat, longitude: all[0].lng, latitudeDelta: 0.02, longitudeDelta: 0.02 }, framed.current ? 400 : 0);
        framed.current = true;
      }
      return;
    }
    const out = !framed.current || (keepInView ? all.some((p) => !inside(region.current, p)) : true);
    if (out) {
      map.fitToCoordinates(all.map((p) => ({ latitude: p.lat, longitude: p.lng })), { edgePadding: PADDING, animated: framed.current });
      framed.current = true;
    }
  }, [all, ready, keepInView]);

  const start = center ?? all[0] ?? { lat: 20, lng: 0 };
  const initial: RNMapProps["initialRegion"] = {
    latitude: start.lat, longitude: start.lng,
    latitudeDelta: all.length ? 0.05 : 60, longitudeDelta: all.length ? 0.05 : 60,
  };

  return (
    <View style={[styles.box, { height, borderColor: theme.colors.border }, style]} accessibilityLabel="Map">
      <RNMap
        ref={ref}
        style={StyleSheet.absoluteFill}
        initialRegion={initial}
        onMapReady={() => setReady(true)}
        onRegionChangeComplete={(r) => { region.current = r; }}
        toolbarEnabled={false}
        rotateEnabled={false}
        pitchEnabled={false}
      >
        {route.length > 1 && (
          <Polyline coordinates={route.map((p) => ({ latitude: p.lat, longitude: p.lng }))} strokeColor={tone("accent")} strokeWidth={5} />
        )}
        {points.map((p) => (
          <Marker
            key={p.id}
            coordinate={{ latitude: p.lat, longitude: p.lng }}
            title={p.label}
            pinColor={tone(p.tone)}
            onPress={() => onPointClick?.(p.id)}
          />
        ))}
      </RNMap>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { overflow: "hidden", borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, width: "100%" },
});
