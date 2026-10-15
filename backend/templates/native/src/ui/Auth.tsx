// The component kit - the frame of the sign-in and sign-up screens (and any screen a person sees before they are
// in). A band in the app's primary colour carries the mark, the name and a line; the form sits on a card that
// overlaps it. Every colour, radius, shadow and size is the theme's: the band is the design's primary, the card
// its corner radius and shadow, the name its heading face.
//
//   <AuthFrame title="Welcome back" tagline="Sign in to continue" footer={<Button variant="ghost">…</Button>}>
//     …the form…
//   </AuthFrame>

import * as React from "react";
import { KeyboardAvoidingView, Platform, ScrollView, View, type StyleProp, type ViewStyle } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { useTheme } from "../theme";
import { Text } from "./Text";
import { APP_NAME } from "../config.generated";

export interface AuthFrameProps {
  /** The card's heading: "Welcome back". */
  title: string;
  /** The line under the app's name in the band. */
  tagline?: string;
  children?: React.ReactNode;
  /** Below the card: the link to the other screen, the language switch. */
  footer?: React.ReactNode;
}

/** The design's brand gradient as a band (the web's `bg-brand-gradient`, 135deg): for a hero or a header that leads
 *  a screen. Its text is `colors.primaryForeground`; keep it to one band per screen, never behind a form or a list. */
export function GradientBand({ children, style, bleed = false }: { children?: React.ReactNode; style?: StyleProp<ViewStyle>; bleed?: boolean }) {
  const theme = useTheme();
  // A BAND IS FINISHED BY DEFAULT: padded from its edges, corners rounded, a small gap between its lines - a writer
  // that put text in a bare band had it flush against the glass (the first real build). `bleed` is for a band that
  // runs to the screen's edge and styles itself (the sign-in frame's).
  const own: ViewStyle = bleed ? {} : { borderRadius: theme.radii.lg, padding: theme.space.xl, gap: theme.space.xs, overflow: "hidden" };
  return (
    <LinearGradient colors={[theme.gradient[0], theme.gradient[1]]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[own, style]}>
      {children}
    </LinearGradient>
  );
}

/** The app's mark: its first letter on the primary colour (a ring keeps it seen on the band), until the owner's own logo is drawn here. */
function Mark() {
  const theme = useTheme();
  const letter = (APP_NAME.trim()[0] ?? "A").toUpperCase();
  return (
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
      style={{ width: 56, height: 56, borderRadius: theme.radii.lg, alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.primary, borderWidth: 2, borderColor: theme.alpha("primaryForeground", 0.55) }}>
      <Text variant="title" style={{ color: theme.colors.primaryForeground }}>{letter}</Text>
    </View>
  );
}

export function AuthFrame({ title, tagline, children, footer }: AuthFrameProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const on = theme.colors.primaryForeground;
  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
      <StatusBar style="light" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={{ flexGrow: 1, paddingBottom: insets.bottom + theme.space.xl }}
          keyboardShouldPersistTaps="handled" keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}>
          <GradientBand bleed style={{
            paddingTop: insets.top + theme.space.xxl, paddingHorizontal: theme.pagePadding,
            paddingBottom: theme.space.xxl + theme.space.xl, gap: theme.space.md,
            borderBottomLeftRadius: theme.radii.lg * 2, borderBottomRightRadius: theme.radii.lg * 2,
          }}>
            <Mark />
            <View style={{ gap: theme.space.xs }}>
              <Text variant="display" accessibilityRole="header" style={{ color: on }}>{APP_NAME}</Text>
              {tagline ? <Text style={{ color: theme.alpha("primaryForeground", 0.85) }}>{tagline}</Text> : null}
            </View>
          </GradientBand>
          <View style={[{
            marginTop: -theme.space.xl, marginHorizontal: theme.pagePadding, padding: theme.space.xl, gap: theme.space.lg,
            backgroundColor: theme.colors.card, borderRadius: theme.radii.lg, borderWidth: theme.borderWidth, borderColor: theme.colors.border,
          }, theme.shadow(2)]}>
            <Text variant="heading" tone="default">{title}</Text>
            {children}
          </View>
          {footer ? <View style={{ marginTop: theme.space.lg, paddingHorizontal: theme.pagePadding, gap: theme.space.md }}>{footer}</View> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}
