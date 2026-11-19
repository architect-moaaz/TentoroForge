// The component kit — a screen whose map IS the screen, the way a ride-hailing driver's app is: the map fills the glass,
// a compact panel floats on top, round buttons float at the side, and a sheet slides up from the bottom. Use it for a
// person who is out and moving (a driver, a courier, a technician on the way), not for a form or a list.
//
//   <MapScreen
//     points={[{ id: "pickup", lat, lng, label: "Pickup", tone: "accent" }]} route={path}
//     top={<FloatingPanel>…who, online, earnings…</FloatingPanel>}
//     controls={<FloatingButton icon="call" label="Call the rider" onPress={call} />}
//   >
//     <BottomSheet snapPoints={[0.24, 0.55]} header={…}>…</BottomSheet>
//   </MapScreen>
//
// It follows the device's own position (the blue dot, the camera) until the person drags the map; a recentre button takes
// it back. It says in words when the location is blocked, cannot be found, or is old. Nothing here is a made-up position:
// with no fix the map shows the places it was given, or the last known spot, and says so.

import * as React from "react";
import { StyleSheet, View, type LayoutChangeEvent } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTheme } from "../theme";
import { MapView, type MapHandle, type MapViewProps } from "../sdk/map";
import { useDevicePosition } from "../sdk/position";
import { Button } from "./Button";
import { FloatingButton, FloatingPanel } from "./Floating";
import { MapScreenContext } from "./MapScreenContext";
import { Text } from "./Text";

export interface MapScreenProps extends Omit<MapViewProps, "height" | "insets" | "style" | "follow" | "showsUser"> {
  /** Follow where this device is (default). `false`: frame the places given instead (a request preview). */
  followUser?: boolean;
  /** Floating at the top: a `FloatingPanel` or several. */
  top?: React.ReactNode;
  /** Round buttons stacked at the right edge, above the recentre button. */
  controls?: React.ReactNode;
  /** Hide the recentre button. */
  noRecenter?: boolean;
  /** The sheet (a `BottomSheet`) and anything else that sits over the bottom of the map. */
  children?: React.ReactNode;
}

export function MapScreen({ followUser = true, top, controls, noRecenter, children, onUserPan, ...map }: MapScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const here = useDevicePosition(followUser);
  const mapRef = React.useRef<MapHandle | null>(null);
  const [room, setRoom] = React.useState(0);
  const [topH, setTopH] = React.useState(0);
  const [shown, setShown] = React.useState(0);
  const [panned, setPanned] = React.useState(false);

  const layout = React.useMemo(() => ({ room, reportShown: setShown }), [room]);
  const follow = followUser && here.position ? here.position : null;
  const high = room > 0 && shown > room * 0.6;

  const warning =
    followUser && here.state === "denied" ? "Location is blocked, so the map cannot follow you."
    : followUser && here.state === "unavailable" ? "Your location could not be found. Move to open sky or check that GPS is on."
    : followUser && here.state === "asking" && !here.position ? "Finding your position…"
    : followUser && here.stale ? "No new location for a while. Showing the last known spot."
    : null;

  return (
    <View
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
      onLayout={(e: LayoutChangeEvent) => setRoom(Math.max(0, e.nativeEvent.layout.height - insets.top))}
    >
      <MapView
        ref={mapRef}
        {...map}
        height="fill"
        showsUser={followUser && here.state === "ok"}
        follow={follow}
        insets={{ top: insets.top + topH, bottom: shown }}
        onUserPan={() => { setPanned(true); onUserPan?.(); }}
      />

      <View pointerEvents="box-none" style={[styles.top, { top: insets.top + 8 }]} onLayout={(e: LayoutChangeEvent) => setTopH(e.nativeEvent.layout.height + 8)}>
        {top}
        {warning ? (
          <FloatingPanel padding="sm" style={styles.warning}>
            <Text variant="caption" tone={here.state === "denied" || here.state === "unavailable" ? "danger" : "muted"}>{warning}</Text>
            {followUser && here.state === "denied" ? <Button size="sm" variant="outline" onPress={here.openSettings}>Open settings</Button> : null}
          </FloatingPanel>
        ) : null}
      </View>

      {/* the buttons ride on the sheet, and step aside once the sheet is tall (they would sit over the panel at the top) */}
      <View pointerEvents={high ? "none" : "box-none"} style={[styles.controls, { bottom: shown + 12, opacity: high ? 0 : 1 }]}>
        {controls}
        {noRecenter || !followUser ? null : (
          <FloatingButton
            icon="locate"
            label="Recentre the map on me"
            variant={panned ? "accent" : "plain"}
            onPress={() => { setPanned(false); mapRef.current?.recenter(here.position ?? undefined); }}
          />
        )}
      </View>

      <MapScreenContext.Provider value={layout}>
        <View pointerEvents="box-none" style={[StyleSheet.absoluteFill, { top: insets.top }]}>{children}</View>
      </MapScreenContext.Provider>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  top: { position: "absolute", left: 12, right: 12, gap: 8 },
  warning: { gap: 8 },
  controls: { position: "absolute", right: 12, gap: 10, alignItems: "flex-end" },
});
