// The app SDK (native) — a map: places as pins, a path as a line, the same props as the web's `MapView`, and the
// extras a map that IS the screen needs.
//
//   <MapView height="fill" showsUser follow={driver} insets={{ top: 96, bottom: 280 }} points={…} route={path} />
//
// react-native-maps draws it: Apple Maps on iPhone, Google Maps on Android (an Android BUILD needs the Maps SDK for
// Android key in `app.json`: `android.config.googleMaps.apiKey`, from GOOGLE_MAPS_ANDROID_KEY; Expo Go's own setup does
// not always draw tiles). A pin's colour is one of the app's own. Under a dark design the map is drawn dark.
//
// `keepInView` frames everything once, then moves the view only when a pin leaves it. `follow` keeps the camera on a
// moving place until the person drags the map (then it stops: `onUserPan`), and `ref.recenter()` takes it back.

import * as React from "react";
import { StyleSheet, View } from "react-native";
import RNMap, { Marker, Polyline, type Region } from "react-native-maps";
import { useTheme } from "../theme";
import type { GeoPoint } from "./geo";
import { isDarkColour, type MapHandle, type MapPoint, type MapViewProps } from "./map-types";

export type { MapPoint, MapViewProps, MapHandle } from "./map-types";

const PADDING = { top: 64, right: 64, bottom: 64, left: 64 };

/** Google's dark style, short: land and water dark, roads a little lighter, labels quiet. */
const DARK_STYLE = [
  { elementType: "geometry", stylers: [{ color: "#1d2230" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#8b93a7" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#1d2230" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#2c3347" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#3a4360" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#10141f" }] },
  { featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
];

function inside(region: Region | null, p: GeoPoint): boolean {
  if (!region) return false;
  return Math.abs(p.lat - region.latitude) <= region.latitudeDelta / 2 && Math.abs(p.lng - region.longitude) <= region.longitudeDelta / 2;
}

export const MapView = React.forwardRef<MapHandle, MapViewProps>(function MapView(
  { points = [], route = [], center, keepInView, onPointClick, height = 320, showsUser, follow, insets, onUserPan, style }, handle,
) {
  const theme = useTheme();
  const ref = React.useRef<RNMap | null>(null);
  const region = React.useRef<Region | null>(null);
  const framed = React.useRef(false);
  const following = React.useRef(true);
  const [ready, setReady] = React.useState(false);
  const dark = isDarkColour(theme.colors.background);
  const top = insets?.top ?? 0, bottom = insets?.bottom ?? 0;

  const all = React.useMemo<GeoPoint[]>(() => [...points, ...route], [points, route]);
  const tone = (t: MapPoint["tone"]) => theme.colors[t === "accent" ? "accent" : t === "muted" ? "mutedForeground" : t === "danger" ? "destructive" : "primary"];

  const fit = React.useCallback(() => {
    const map = ref.current;
    if (!map || all.length < 2) return;
    map.fitToCoordinates(all.map((p) => ({ latitude: p.lat, longitude: p.lng })), { edgePadding: { ...PADDING, top: PADDING.top + top, bottom: PADDING.bottom + bottom }, animated: framed.current });
    framed.current = true;
  }, [all, top, bottom]);

  React.useImperativeHandle(handle, () => ({
    recenter: (point) => {
      const to = point ?? follow;
      if (!to || !ref.current) return;
      following.current = true;
      ref.current.animateCamera({ center: { latitude: to.lat, longitude: to.lng }, zoom: 16 }, { duration: 500 });
    },
    fit,
  }), [follow, fit]);

  // The camera stays on a moving place until the person moves the map.
  React.useEffect(() => {
    if (!ready || !follow || !following.current || !ref.current) return;
    ref.current.animateCamera({ center: { latitude: follow.lat, longitude: follow.lng }, ...(follow.heading != null ? { heading: follow.heading } : {}) }, { duration: 600 });
  }, [ready, follow?.lat, follow?.lng, follow?.heading]);

  // The pins and the path, framed once and kept in view.
  React.useEffect(() => {
    const map = ref.current;
    if (!map || !ready || all.length === 0 || (follow && following.current)) return;
    if (all.length === 1) {
      if (!framed.current || !inside(region.current, all[0])) {
        map.animateToRegion({ latitude: all[0].lat, longitude: all[0].lng, latitudeDelta: 0.02, longitudeDelta: 0.02 }, framed.current ? 400 : 0);
        framed.current = true;
      }
      return;
    }
    if (!framed.current || (keepInView ? all.some((p) => !inside(region.current, p)) : true)) fit();
  }, [all, ready, keepInView, fit, follow]);

  const start = center ?? follow ?? all[0] ?? { lat: 20, lng: 0 };
  const fill = height === "fill";

  return (
    <View style={[fill ? StyleSheet.absoluteFill : styles.box, !fill && { height: height as number, borderColor: theme.colors.border }, style as object]} accessibilityLabel="Map">
      <RNMap
        ref={ref}
        style={StyleSheet.absoluteFill}
        initialRegion={{ latitude: start.lat, longitude: start.lng, latitudeDelta: all.length || follow ? 0.05 : 60, longitudeDelta: all.length || follow ? 0.05 : 60 }}
        onMapReady={() => setReady(true)}
        onRegionChangeComplete={(r) => { region.current = r; }}
        onPanDrag={() => { if (following.current) { following.current = false; onUserPan?.(); } }}
        mapPadding={{ top, bottom, left: 0, right: 0 }}
        showsUserLocation={showsUser}
        showsMyLocationButton={false}
        showsCompass={false}
        toolbarEnabled={false}
        rotateEnabled={!!follow}
        pitchEnabled={false}
        customMapStyle={dark ? DARK_STYLE : undefined}
        userInterfaceStyle={dark ? "dark" : "light"}
      >
        {route.length > 1 && (
          <Polyline coordinates={route.map((p) => ({ latitude: p.lat, longitude: p.lng }))} strokeColor={tone("accent")} strokeWidth={6} />
        )}
        {points.map((p) => (
          <Marker
            key={p.id}
            coordinate={{ latitude: p.lat, longitude: p.lng }}
            title={p.label}
            pinColor={tone(p.tone)}
            {...(p.heading != null ? { rotation: p.heading, flat: true, anchor: { x: 0.5, y: 0.5 } } : {})}
            onPress={() => onPointClick?.(p.id)}
          />
        ))}
      </RNMap>
    </View>
  );
});

const styles = StyleSheet.create({
  box: { overflow: "hidden", borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, width: "100%" },
});
