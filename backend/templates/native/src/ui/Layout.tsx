// The component kit — layout. Spacing is one scale (`space` in theme.ts: xs 4,
// sm 8, md 12, lg 16, xl 24, xxl 32) and these are how a screen uses it, so no
// screen writes a margin in points.
//
//   <Stack gap="lg" padding="lg"> … </Stack>        a column
//   <Row gap="sm" justify="between"> … </Row>       a row (wraps with `wrap`)
//   <Spacer />                                       flexible gap; <Spacer size="xl" /> a fixed one
//   <Card onPress={…}> … </Card>                     a surface; pressable when it has onPress
//   <Divider />

import * as React from "react";
import { Pressable, View, type StyleProp, type ViewProps, type ViewStyle } from "react-native";
import { useTheme, type Space } from "../theme";

type Gap = Space | number;

function px(theme: { space: Record<Space, number> }, v: Gap | undefined): number | undefined {
  if (v === undefined) return undefined;
  return typeof v === "number" ? v : theme.space[v];
}

const JUSTIFY = { start: "flex-start", center: "center", end: "flex-end", between: "space-between", around: "space-around" } as const;
const ALIGN = { start: "flex-start", center: "center", end: "flex-end", stretch: "stretch", baseline: "baseline" } as const;

export interface StackProps extends ViewProps {
  gap?: Gap;
  padding?: Gap;
  /** Cross-axis alignment (default stretch). */
  align?: keyof typeof ALIGN;
  justify?: keyof typeof JUSTIFY;
  /** Take the room left in the parent. */
  flex?: boolean;
}

/** A column. */
export function Stack({ gap, padding, align, justify, flex, style, ...rest }: StackProps) {
  const theme = useTheme();
  return (
    <View {...rest} style={[
      { gap: px(theme, gap), padding: px(theme, padding), alignItems: align ? ALIGN[align] : undefined,
        justifyContent: justify ? JUSTIFY[justify] : undefined, flex: flex ? 1 : undefined },
      style,
    ]} />
  );
}

export interface RowProps extends StackProps {
  wrap?: boolean;
}

/** A row; centres its children vertically unless told otherwise. */
export function Row({ gap, padding, align = "center", justify, flex, wrap, style, ...rest }: RowProps) {
  const theme = useTheme();
  return (
    <View {...rest} style={[
      { flexDirection: "row", flexWrap: wrap ? "wrap" : "nowrap", gap: px(theme, gap), padding: px(theme, padding),
        alignItems: ALIGN[align], justifyContent: justify ? JUSTIFY[justify] : undefined, flex: flex ? 1 : undefined },
      style,
    ]} />
  );
}

/** Space between things: flexible by default (pushes the rest apart), or a fixed `size`. */
export function Spacer({ size }: { size?: Gap }) {
  const theme = useTheme();
  const n = px(theme, size);
  return <View accessibilityElementsHidden importantForAccessibility="no" style={n === undefined ? { flex: 1 } : { width: n, height: n }} />;
}

export function Divider({ style }: { style?: StyleProp<ViewStyle> }) {
  const theme = useTheme();
  return <View accessibilityElementsHidden importantForAccessibility="no" style={[{ height: 1, backgroundColor: theme.colors.border, alignSelf: "stretch" }, style]} />;
}

export interface CardProps extends ViewProps {
  /** Pressable: the whole card is one button. */
  onPress?: () => void;
  accessibilityLabel?: string;
  /** `filled` (default) is a surface with a hairline; `muted` a quiet one; `inverse` a dark one. */
  variant?: "filled" | "muted" | "inverse";
  padding?: Gap;
}

export function Card({ onPress, variant = "filled", padding = "lg", style, accessibilityLabel, children, ...rest }: CardProps) {
  const theme = useTheme();
  const c = theme.colors;
  const surface: ViewStyle = {
    backgroundColor: variant === "inverse" ? c.inverse : variant === "muted" ? c.muted : c.card,
    borderColor: theme.alpha("border", 0.7), borderWidth: variant === "inverse" ? 0 : 1, borderRadius: theme.radius + 8, padding: px(theme, padding),
    ...(variant === "filled" ? theme.shadow(1) : {}),
  };
  if (onPress) {
    return (
      <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={accessibilityLabel}
        style={({ pressed }) => [surface, { minHeight: theme.touch, transform: [{ scale: pressed ? 0.985 : 1 }] }, style as StyleProp<ViewStyle>]}>
        {children}
      </Pressable>
    );
  }
  return (
    <View {...rest} accessible={accessibilityLabel ? true : rest.accessible} accessibilityLabel={accessibilityLabel} style={[surface, style]}>
      {children}
    </View>
  );
}
