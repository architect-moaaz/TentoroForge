// The component kit - icons. A glyph from the Ionicons set (shipped with Expo, no native module to
// build), coloured from the theme. An icon beside a word makes it findable at a glance; an icon alone is
// a button and needs `accessibilityLabel` on the Pressable that holds it.
//
//   <Icon name="add" />                         a plus, in the primary colour
//   <Icon name="checkmark-circle" tone="success" size={20} />
//
// Names people reach for: add, add-circle, remove, close, checkmark, checkmark-circle, trash-outline,
// create-outline, pencil, search, filter, options, list, grid, calendar-outline, time-outline, person-outline,
// people-outline, mail-outline, call-outline, location-outline, map-outline, home-outline, settings-outline,
// notifications-outline, star, star-outline, heart-outline, bookmark-outline, cart-outline, card-outline,
// cash-outline, stats-chart, trending-up, document-text-outline, folder-outline, image-outline, camera-outline,
// cloud-upload-outline, download-outline, share-outline, ellipsis-horizontal, chevron-forward, chevron-back,
// chevron-down, arrow-forward, arrow-back, play, pause, refresh, information-circle-outline, alert-circle-outline,
// construct, hammer-outline, briefcase-outline, flag-outline, flash-outline, shield-checkmark-outline, lock-closed-outline.

import * as React from "react";
import { Ionicons } from "@expo/vector-icons";
import { useTheme } from "../theme";

export type IconName = keyof typeof Ionicons.glyphMap;
export type IconTone = "default" | "muted" | "primary" | "danger" | "success" | "warning" | "inverse" | "accent";

export function Icon({ name, size = 20, tone = "primary", color }: { name: IconName; size?: number; tone?: IconTone; color?: string }) {
  const theme = useTheme();
  const c = theme.colors;
  const byTone: Record<IconTone, string> = {
    default: c.foreground, muted: c.mutedForeground, primary: c.primary, danger: c.destructive,
    success: c.success, warning: c.warning, inverse: c.inverseForeground, accent: c.accent,
  };
  return <Ionicons name={name} size={size} color={color ?? byTone[tone]} accessibilityElementsHidden importantForAccessibility="no" />;
}
