// The component kit — the button. Variants are the web's (primary, accent,
// secondary, outline, ghost, danger); `accent` when pressing it is the one thing
// the screen is for. A touch target is never under 44 points, `loading` shows a
// spinner and ignores presses (a double tap must not run a workflow twice), and
// a screen reader hears the label and "busy" / "dimmed" states.
//
//   <Button onPress={save} loading={pending}>Save</Button>
//   <Button variant="danger" size="sm" onPress={…}>Delete</Button>

import * as React from "react";
import { ActivityIndicator, Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import { useTheme } from "../theme";
import { Text } from "./Text";

export type ButtonVariant = "primary" | "accent" | "secondary" | "outline" | "ghost" | "danger";

export interface ButtonProps {
  children: React.ReactNode;
  onPress?: () => void;
  variant?: ButtonVariant;
  /** `sm` is a compact button that is still a full 44 point target. */
  size?: "sm" | "md";
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
}

export function Button({ children, onPress, variant = "primary", size = "md", loading = false, disabled = false, fullWidth = false, accessibilityLabel, style }: ButtonProps) {
  const theme = useTheme();
  const c = theme.colors;
  const tones: Record<ButtonVariant, { bg: string; fg: string; border: string }> = {
    primary: { bg: c.primary, fg: c.primaryForeground, border: c.primary },
    accent: { bg: c.accent, fg: c.accentForeground, border: c.accent },
    secondary: { bg: c.secondary, fg: c.secondaryForeground, border: c.secondary },
    outline: { bg: "transparent", fg: c.foreground, border: c.border },
    ghost: { bg: "transparent", fg: c.primary, border: "transparent" },
    danger: { bg: c.destructive, fg: c.destructiveForeground, border: c.destructive },
  };
  const t = tones[variant];
  const off = disabled || loading;
  return (
    <Pressable
      onPress={off ? undefined : onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? (typeof children === "string" ? children : undefined)}
      accessibilityState={{ disabled: off, busy: loading }}
      style={({ pressed }) => [
        styles.base,
        { backgroundColor: t.bg, borderColor: t.border, borderRadius: theme.radius, minHeight: theme.touch,
          paddingHorizontal: size === "sm" ? 14 : 20, opacity: off ? 0.55 : pressed ? 0.85 : 1,
          alignSelf: fullWidth ? "stretch" : "flex-start" },
        style,
      ]}>
      <View style={styles.content}>
        {loading ? <ActivityIndicator size="small" color={t.fg} /> : null}
        {typeof children === "string"
          ? <Text variant={size === "sm" ? "caption" : "label"} weight="semibold" style={{ color: t.fg, fontSize: size === "sm" ? 13 : 15 }}>{children}</Text>
          : children}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: { alignItems: "center", justifyContent: "center", borderWidth: 1 },
  content: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
});
