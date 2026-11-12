// The component kit — things that float over a map: a rounded `FloatingPanel` (the status bar at the top of a driver's
// map, a banner) and a round `FloatingButton` (recentre, call, navigate). Both are the design's own: card colour, border,
// corner and shadow come from the theme, and a button is never under 48 points so a thumb finds it in a moving car.
//
//   <FloatingPanel><Row>…avatar, online switch, earnings…</Row></FloatingPanel>
//   <FloatingButton icon="locate" label="Recentre" onPress={recentre} />

import * as React from "react";
import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import { useTheme, space, type Theme } from "../theme";
import { Icon, type IconName } from "./Icon";

type Space = keyof typeof space;

export interface FloatingPanelProps {
  children?: React.ReactNode;
  padding?: Space;
  style?: StyleProp<ViewStyle>;
}

export function FloatingPanel({ children, padding = "md", style }: FloatingPanelProps) {
  const theme = useTheme();
  return (
    <View
      style={[
        { backgroundColor: theme.colors.card, borderRadius: theme.radii.lg, padding: space[padding],
          borderColor: theme.alpha("border", 0.7), borderWidth: theme.borderWidth, ...theme.shadow(2) },
        style,
      ]}
    >
      {children}
    </View>
  );
}

export interface FloatingButtonProps {
  icon: IconName;
  /** What a screen reader says: required, because the button is only a picture. */
  label: string;
  onPress: () => void;
  /** `accent` is the one thing to do; `plain` is a control on the map. */
  variant?: "plain" | "accent";
  size?: number;
  style?: StyleProp<ViewStyle>;
}

export function FloatingButton({ icon, label, onPress, variant = "plain", size = 52, style }: FloatingButtonProps) {
  const theme = useTheme();
  const accent = variant === "accent";
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={6}
      style={({ pressed }: { pressed: boolean }) => [
        styles.round,
        {
          width: Math.max(48, size), height: Math.max(48, size), borderRadius: Math.max(48, size) / 2,
          backgroundColor: accent ? theme.colors.accent : theme.colors.card,
          borderColor: theme.alpha("border", 0.7), borderWidth: accent ? 0 : theme.borderWidth,
          opacity: pressed ? 0.85 : 1, ...theme.shadow(2),
        },
        style,
      ]}
    >
      <Icon name={icon} size={24} tone={accent ? "inverse" : "default"} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  round: { alignItems: "center", justifyContent: "center" },
});

export type { Theme };
