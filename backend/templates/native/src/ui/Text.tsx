// The component kit — text. Every string a screen shows goes through here, so
// type size, weight and colour come from one scale and one palette, and a
// screen reader announces headings as headings.
//
//   <Title>Orders</Title>
//   <Text variant="caption" tone="muted">Updated just now</Text>
//
// variants: display (hero number), title (screen title), heading (section),
//           body (default), label (form label, row title), caption (small print)
// tones:    default, muted, primary, danger, success, warning, inverse

import * as React from "react";
import { Text as RNText, type TextProps as RNTextProps, type TextStyle } from "react-native";
import { useTheme, type Theme } from "../theme";

export type TextVariant = "display" | "title" | "heading" | "body" | "label" | "caption";
export type TextTone = "default" | "muted" | "primary" | "danger" | "success" | "warning" | "inverse";

export interface TextProps extends RNTextProps {
  variant?: TextVariant;
  tone?: TextTone;
  weight?: "regular" | "medium" | "semibold" | "bold";
  align?: "left" | "center" | "right";
}

const SIZES: Record<TextVariant, { fontSize: number; lineHeight: number; fontWeight: TextStyle["fontWeight"] }> = {
  display: { fontSize: 32, lineHeight: 38, fontWeight: "700" },
  title: { fontSize: 24, lineHeight: 30, fontWeight: "700" },
  heading: { fontSize: 18, lineHeight: 24, fontWeight: "600" },
  body: { fontSize: 16, lineHeight: 22, fontWeight: "400" },
  label: { fontSize: 14, lineHeight: 20, fontWeight: "600" },
  caption: { fontSize: 12, lineHeight: 16, fontWeight: "400" },
};

const WEIGHTS: Record<NonNullable<TextProps["weight"]>, TextStyle["fontWeight"]> = {
  regular: "400", medium: "500", semibold: "600", bold: "700",
};

function toneColor(theme: Theme, tone: TextTone): string {
  const c = theme.colors;
  switch (tone) {
    case "muted": return c.mutedForeground;
    case "primary": return c.primary;
    case "danger": return c.destructive;
    case "success": return c.success;
    case "warning": return c.warning;
    case "inverse": return c.inverseForeground;
    default: return c.foreground;
  }
}

export function Text({ variant = "body", tone = "default", weight, align, style, accessibilityRole, ...rest }: TextProps) {
  const theme = useTheme();
  const size = SIZES[variant];
  const heading = variant === "display" || variant === "title" || variant === "heading";
  const family = heading ? theme.fonts.heading ?? theme.fonts.body : theme.fonts.body;
  return (
    <RNText
      {...rest}
      accessibilityRole={accessibilityRole ?? (heading ? "header" : undefined)}
      style={[
        { color: toneColor(theme, tone), fontSize: size.fontSize, lineHeight: size.lineHeight, fontWeight: weight ? WEIGHTS[weight] : size.fontWeight },
        family ? { fontFamily: family } : null,
        align ? { textAlign: align } : null,
        style,
      ]}
    />
  );
}

/** A screen's or section's title: `variant="title"`, announced as a header. */
export function Title(props: Omit<TextProps, "variant">) {
  return <Text variant="title" {...props} />;
}
