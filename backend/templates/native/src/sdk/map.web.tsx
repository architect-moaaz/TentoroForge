// The app SDK (native) — the map, as the WEB picture of a phone app draws it (the Editor's phone preview and `expo start
// --web`). react-native-maps draws on a phone only; importing it for the web fails the whole bundle, so the web gets this
// stand-in with the same props and the same handle: a card that says where the pins are, never a blank box or a crash.
// The real map is `map.tsx`, which a phone uses.

import * as React from "react";
import { StyleSheet, View } from "react-native";
import { useTheme } from "../theme";
import { Text } from "../ui/Text";
import { distanceKm, formatDistance } from "./geo";
import type { MapHandle, MapPoint, MapViewProps } from "./map-types";

export type { MapPoint, MapViewProps, MapHandle } from "./map-types";

export const MapView = React.forwardRef<MapHandle, MapViewProps>(function MapView(
  { points = [], route = [], follow, onPointClick, height = 320, style }, handle,
) {
  const theme = useTheme();
  React.useImperativeHandle(handle, () => ({ recenter: () => undefined, fit: () => undefined }), []);
  const tone = (t: MapPoint["tone"]) => theme.colors[t === "accent" ? "accent" : t === "muted" ? "mutedForeground" : t === "danger" ? "destructive" : "primary"];
  const length = route.length > 1 ? route.slice(1).reduce((km, p, i) => km + (distanceKm(route[i], p) ?? 0), 0) : 0;
  const fill = height === "fill";
  return (
    <View
      style={[fill ? StyleSheet.absoluteFill : { minHeight: Math.min(height as number, 200), borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, width: "100%" },
        styles.box, { borderColor: theme.colors.border, backgroundColor: theme.colors.muted }, style as object]}
      accessibilityLabel="Map"
    >
      <Text variant="label">Map</Text>
      <Text variant="caption" tone="muted">The live map is drawn on the phone (Expo Go or the app). This is how the places line up here.</Text>
      {follow ? <Text variant="caption">You · {follow.lat.toFixed(4)}, {follow.lng.toFixed(4)}</Text> : null}
      {points.map((p) => (
        <View key={p.id} style={styles.row}>
          <View style={[styles.dot, { backgroundColor: tone(p.tone) }]} />
          <Text variant="caption" onPress={() => onPointClick?.(p.id)}>{p.label ?? p.id} · {p.lat.toFixed(4)}, {p.lng.toFixed(4)}</Text>
        </View>
      ))}
      {route.length > 1 ? <Text variant="caption" tone="muted">Road shown: {formatDistance(length)} along the line</Text> : null}
    </View>
  );
});

const styles = StyleSheet.create({
  box: { padding: 12, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  dot: { width: 10, height: 10, borderRadius: 5 },
});
