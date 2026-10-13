// The component kit — the screen frame. Every screen is one `<Screen>`: it
// keeps content out from under the notch, the status bar and the home bar (safe
// area), lifts a form above the keyboard, scrolls, pulls to refresh, and draws
// the title bar with a back button when there is a screen to go back to.
//
//   <Screen title="Orders" right={<Button size="sm" onPress={…}>New</Button>}
//           loading={orders.loading} error={orders.error} onRetry={orders.refetch}
//           onRefresh={orders.refetch} refreshing={orders.refreshing}>
//     …content…
//   </Screen>
//
// WHAT IT SHOWS, in this order: `loading` -> a spinner; `error` -> the sentence
// and Try again (`onRetry`); `empty` (a node) -> that, in place of the content;
// else the content. A screen that fills the whole frame with its own list
// (`<ListView />`) passes `scroll={false}` — two scrollers nested is a bug.

import * as React from "react";
import { KeyboardAvoidingView, Platform, Pressable, RefreshControl, ScrollView, View, type StyleProp, type ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { useTheme } from "../theme";
import { useNav } from "../sdk/nav";
import { Text } from "./Text";
import { ErrorState, Loading } from "./States";

export interface HeaderProps {
  title?: string;
  subtitle?: string;
  /** Show the back button. Default: when there is a screen to go back to. */
  back?: boolean;
  right?: React.ReactNode;
}

/** The title bar: back, title (and a line under it), actions on the right. */
export function Header({ title, subtitle, back, right }: HeaderProps) {
  const theme = useTheme();
  const nav = useNav();
  const showBack = back ?? nav.canGoBack();
  if (!title && !showBack && !right) return null;
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.sm, paddingHorizontal: theme.space.lg, paddingVertical: theme.space.sm, minHeight: 56 }}>
      {showBack ? (
        <Pressable onPress={nav.back} accessibilityRole="button" accessibilityLabel="Back" hitSlop={8}
          style={{ width: theme.touch, height: theme.touch, marginLeft: -theme.space.sm, alignItems: "center", justifyContent: "center" }}>
          <Text style={{ fontSize: 30, lineHeight: 32, color: theme.colors.primary }}>‹</Text>
        </Pressable>
      ) : null}
      <View style={{ flex: 1 }}>
        {title ? <Text variant="title" numberOfLines={1} style={{ fontSize: 22, lineHeight: 28 }}>{title}</Text> : null}
        {subtitle ? <Text variant="caption" tone="muted" numberOfLines={1}>{subtitle}</Text> : null}
      </View>
      {right ? <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.sm }}>{right}</View> : null}
    </View>
  );
}

export interface ScreenProps extends HeaderProps {
  children?: React.ReactNode;
  /** Scroll the content (default). `false` when the content is its own list. */
  scroll?: boolean;
  /** Padding around the content (default true). */
  padded?: boolean;
  /** Gap between direct children when padded (default `lg`). */
  gap?: number;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Shown instead of the content: `<Empty title="No orders yet" />`. */
  empty?: React.ReactNode;
  /** Pull-to-refresh. */
  onRefresh?: () => void;
  refreshing?: boolean;
  /** Something fixed under the content (a sticky submit bar). */
  footer?: React.ReactNode;
  contentStyle?: StyleProp<ViewStyle>;
}

export function Screen({
  title, subtitle, back, right, children, scroll = true, padded = true, gap, loading, error, onRetry, empty, onRefresh, refreshing = false, footer, contentStyle,
}: ScreenProps) {
  const theme = useTheme();
  const body = loading ? <Loading />
    : error ? <ErrorState message={error} onRetry={onRetry} />
    : empty ? empty
    : children;
  const pad = padded ? theme.space.lg : 0;
  const content = scroll ? (
    <ScrollView
      style={{ flex: 1 }}
      contentContainerStyle={[{ padding: pad, paddingTop: padded ? theme.space.sm : 0, gap: gap ?? theme.space.lg, flexGrow: 1 }, contentStyle]}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}
      refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.colors.primary} colors={[theme.colors.primary]} /> : undefined}>
      {body}
    </ScrollView>
  ) : (
    <View style={[{ flex: 1, paddingHorizontal: pad }, contentStyle]}>{body}</View>
  );
  return (
    <SafeAreaView edges={["top", "left", "right", "bottom"]} style={{ flex: 1, backgroundColor: theme.colors.background }}>
      <StatusBar style="dark" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <Header title={title} subtitle={subtitle} back={back} right={right} />
        {content}
        {footer ? <View style={{ padding: theme.space.lg, borderTopWidth: 1, borderTopColor: theme.colors.border, backgroundColor: theme.colors.card }}>{footer}</View> : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
