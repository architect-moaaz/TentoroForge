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
export type TextTone = "default" | "accent" | "muted" | "primary" | "danger" | "success" | "warning" | "inverse";

export interface TextProps extends RNTextProps {
  variant?: TextVariant;
  tone?: TextTone;
  weight?: "regular" | "medium" | "semibold" | "bold";
  align?: "left" | "center" | "right";
}

const SIZES: Record<TextVariant, { fontSize: number; lineHeight: number; fontWeight: TextStyle["fontWeight"] }> = {
  display: { fontSize: 34, lineHeight: 40, fontWeight: "700" },
  title: { fontSize: 28, lineHeight: 34, fontWeight: "700" },
  heading: { fontSize: 19, lineHeight: 25, fontWeight: "600" },
  body: { fontSize: 16, lineHeight: 23, fontWeight: "400" },
  label: { fontSize: 14, lineHeight: 20, fontWeight: "600" },
  caption: { fontSize: 12, lineHeight: 17, fontWeight: "400" },
};

const WEIGHT_OF: Record<string, "regular" | "medium" | "semibold" | "bold"> = {
  "400": "regular", "500": "medium", "600": "semibold", "700": "bold",
};

const WEIGHTS: Record<NonNullable<TextProps["weight"]>, TextStyle["fontWeight"]> = {
  regular: "400", medium: "500", semibold: "600", bold: "700",
};

function toneColor(theme: Theme, tone: TextTone): string {
  const c = theme.colors;
  switch (tone) {
    case "muted": return c.mutedForeground;
    case "primary": return c.primary;
    case "accent": return c.accent;
    case "danger": return c.destructive;
    case "success": return c.success;
    case "warning": return c.warning;
    case "inverse": return c.inverseForeground;
    default: return c.foreground;
  }
}

export function Text({ variant = "body", tone, weight: asked, align, style, accessibilityRole, ...rest }: TextProps) {
  const theme = useTheme();
  const base = SIZES[variant];
  const heading = variant === "display" || variant === "title" || variant === "heading";
  // THE DESIGN'S HEADINGS: its weight for every heading, its colour for a page title, its title size.
  const weight = asked ?? (heading ? theme.heading.weight : undefined);
  const page = variant === "display" || variant === "title";
  const size = page && theme.heading.titleSize
    ? { ...base, fontSize: theme.heading.titleSize / theme.typeScale, lineHeight: Math.round(theme.heading.titleSize * 1.2) / theme.typeScale }
    : base;
  const fontWeight = weight ? WEIGHTS[weight] : size.fontWeight;
  // A custom typeface is one file per weight: pick the file, and leave `fontWeight` out (on Android the
  // two together fall back to the system font). On the system font, `fontWeight` does the work.
  const face = theme.font(weight ?? WEIGHT_OF[String(size.fontWeight)] ?? "regular", heading ? "heading" : "body");
  return (
    <RNText
      {...rest}
      accessibilityRole={accessibilityRole ?? (heading ? "header" : undefined)}
      style={[
        { color: toneColor(theme, tone ?? (page ? theme.heading.tone : "default")), fontSize: Math.round(size.fontSize * theme.typeScale * 10) / 10, lineHeight: Math.round(size.lineHeight * theme.typeScale * 10) / 10 },
        face.fontFamily ? face : { fontWeight },
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
