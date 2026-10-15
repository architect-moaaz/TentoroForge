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
import { Icon, type IconName } from "./Icon";

export type ButtonVariant = "primary" | "accent" | "secondary" | "outline" | "ghost" | "danger";

export interface ButtonProps {
  children: React.ReactNode;
  onPress?: () => void;
  variant?: ButtonVariant;
  /** `sm` is a compact button that is still a full 44 point target. */
  size?: "sm" | "md";
  /** A glyph before the label (`Icon` names): `<Button icon="add">Add job</Button>`. */
  icon?: IconName;
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
}

export function Button({ children, onPress, variant = "primary", size = "md", icon, loading = false, disabled = false, fullWidth = false, accessibilityLabel, style }: ButtonProps) {
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
      hitSlop={size === "sm" ? 6 : 0}
      style={({ pressed }) => [
        styles.base,
        { backgroundColor: t.bg, borderColor: t.border, borderRadius: theme.radii.md, borderWidth: theme.borderWidth,
          minHeight: size === "sm" ? 38 : theme.touch + 4, paddingHorizontal: size === "sm" ? 14 : 22,
          opacity: off ? 0.55 : 1, transform: [{ scale: pressed ? 0.97 : 1 }],
          alignSelf: fullWidth ? "stretch" : "flex-start" },
        variant === "primary" || variant === "accent" || variant === "danger" ? theme.shadow(1) : null,
        pressed && (variant === "ghost" || variant === "outline") ? { backgroundColor: theme.colors.muted } : null,
        style,
      ]}>
      <View style={styles.content}>
        {loading ? <ActivityIndicator size="small" color={t.fg} /> : icon ? <Icon name={icon} size={size === "sm" ? 16 : 18} color={t.fg} /> : null}
        {typeof children === "string"
          ? <Text variant={size === "sm" ? "caption" : "label"} weight="semibold" style={{ color: t.fg, fontSize: size === "sm" ? 13 : 15 }}>{children}</Text>
          : children}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: { alignItems: "center", justifyContent: "center" },
  content: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
});
