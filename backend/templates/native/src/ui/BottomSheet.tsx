// The component kit — a bottom sheet that stays on the screen: it does not dim or block what is behind it (a live map), and
// the person drags it between resting heights. `Sheet` is the other one: a pop-up over a dimmed screen for a picker.
//
//   <MapScreen …>
//     <BottomSheet snapPoints={[0.2, 0.5, 0.88]} header={<Text variant="heading">You're online</Text>}>
//       …details, one primary button…
//     </BottomSheet>
//   </MapScreen>
//
// `snapPoints` are resting heights: a number of 1 or less is a share of the room there is, more is points. `index` makes it
// controlled (a new request opens it); without it the sheet keeps its own. Drag the handle or the header; a flick carries
// it on. The content scrolls only when the sheet is open to its tallest height. Standalone it fills its parent; inside a
// `MapScreen` it knows the room there is and tells the map how much it covers.

import * as React from "react";
import { Animated, LayoutChangeEvent, PanResponder, ScrollView, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTheme } from "../theme";
import { dragShown, settleSheet, sheetHeights } from "./logic";
import { MapScreenContext } from "./MapScreenContext";

export interface BottomSheetProps {
  snapPoints?: number[];
  /** Controlled resting height (an index into `snapPoints`). */
  index?: number;
  defaultIndex?: number;
  onIndexChange?: (index: number) => void;
  /** Always visible, under the handle: the drag area too. */
  header?: React.ReactNode;
  children?: React.ReactNode;
}

export function BottomSheet({ snapPoints = [0.22, 0.5, 0.88], index, defaultIndex = 0, onIndexChange, header, children }: BottomSheetProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const layout = React.useContext(MapScreenContext);
  const [own, setOwn] = React.useState(0);
  const room = layout.room || own;
  const heights = React.useMemo(() => sheetHeights(snapPoints, room || 600), [snapPoints.join(","), room]);
  const [inner, setInner] = React.useState(defaultIndex);
  const at = Math.min(index ?? inner, heights.length - 1);
  const top = heights[heights.length - 1] ?? 0;

  const shown = React.useRef(new Animated.Value(heights[at] ?? 0)).current;
  const current = React.useRef(heights[at] ?? 0);
  const start = React.useRef(0);
  React.useEffect(() => {
    const id = shown.addListener(({ value }) => { current.current = value; });
    return () => shown.removeListener(id);
  }, [shown]);

  const rest = React.useCallback((i: number, spring = true) => {
    const to = heights[i] ?? 0;
    (spring
      ? Animated.spring(shown, { toValue: to, useNativeDriver: false, bounciness: 3, speed: 14 })
      : Animated.timing(shown, { toValue: to, duration: 0, useNativeDriver: false })
    ).start();
    layout.reportShown(to);
  }, [heights, layout, shown]);

  // A new height asked for from outside, or a new room, moves the sheet there.
  React.useEffect(() => { rest(at); }, [at, heights.join(","), rest]);

  const pan = React.useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: (_e: unknown, g: { dy: number }) => Math.abs(g.dy) > 4,
    onPanResponderGrant: () => { shown.stopAnimation((v: number) => { start.current = v; }); },
    onPanResponderMove: (_e: unknown, g: { dy: number }) => { shown.setValue(dragShown(start.current, g.dy, heights)); },
    onPanResponderRelease: (_e: unknown, g: { vy: number }) => {
      const i = settleSheet(current.current, g.vy, heights);
      setInner(i);
      onIndexChange?.(i);
      rest(i);
    },
  }), [heights, onIndexChange, rest, shown]);

  const translateY = shown.interpolate({ inputRange: [0, Math.max(top, 1)], outputRange: [top, 0], extrapolate: "extend" });
  const open = at === heights.length - 1;

  return (
    <View
      pointerEvents="box-none"
      style={StyleSheet.absoluteFill}
      onLayout={(e: LayoutChangeEvent) => { if (!layout.room) setOwn(e.nativeEvent.layout.height); }}
    >
      <Animated.View
        style={[
          styles.sheet,
          {
            height: top + insets.bottom, paddingBottom: insets.bottom, transform: [{ translateY }],
            backgroundColor: theme.colors.card, borderTopLeftRadius: theme.radii.lg, borderTopRightRadius: theme.radii.lg,
            borderColor: theme.alpha("border", 0.7), borderWidth: theme.borderWidth, borderBottomWidth: 0, ...theme.shadow(3),
          },
        ]}
      >
        <View {...pan.panHandlers} accessibilityRole="adjustable" accessibilityLabel="Drag to open or close">
          <View style={styles.handleArea}>
            <View style={[styles.handle, { backgroundColor: theme.alpha("mutedForeground", 0.5) }]} />
          </View>
          {header ? <View style={styles.header}>{header}</View> : null}
        </View>
        <ScrollView scrollEnabled={open} showsVerticalScrollIndicator={false} contentContainerStyle={styles.body}>
          {children}
        </ScrollView>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: { position: "absolute", left: 0, right: 0, bottom: 0, overflow: "hidden" },
  handleArea: { alignItems: "center", paddingTop: 10, paddingBottom: 8 },
  handle: { width: 40, height: 5, borderRadius: 3 },
  header: { paddingHorizontal: 16, paddingBottom: 8 },
  body: { paddingHorizontal: 16, paddingBottom: 16, gap: 12 },
});
