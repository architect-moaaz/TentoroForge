// The component kit — the three states every screen has besides "showing data":
// loading, empty, and wrong. A screen that handles none of them shows a blank
// white page the moment the network is slow, a list has no rows, or a read fails,
// and "blank" reads as "broken". `Screen` and `ListView` draw these for you from
// their `loading` / `error` / `empty` props; use them directly for a section.
//
//   <Loading />                                   spinner
//   <Empty title="No orders yet" message="Orders you place appear here." action={<Button …/>} />
//   <ErrorState message={error} onRetry={refetch} />   says what failed, and retries

import * as React from "react";
import { ActivityIndicator, View } from "react-native";
import { useTheme } from "../theme";
import { Text } from "./Text";
import { Button } from "./Button";
import { Icon, type IconName } from "./Icon";

export function Loading({ label = "Loading" }: { label?: string }) {
  const theme = useTheme();
  return (
    <View accessibilityRole="progressbar" accessibilityLabel={label} style={{ flex: 1, minHeight: 160, alignItems: "center", justifyContent: "center", padding: theme.space.xl }}>
      <ActivityIndicator size="large" color={theme.colors.primary} />
    </View>
  );
}

export function Empty({ title, message, action, icon }: { title: string; message?: string; action?: React.ReactNode; icon?: IconName }) {
  const theme = useTheme();
  return (
    <View style={{ flex: 1, minHeight: 200, alignItems: "center", justifyContent: "center", padding: theme.space.xl, gap: theme.space.sm }}>
      {icon ? (
        <View style={{ width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.muted, marginBottom: theme.space.sm }}>
          <Icon name={icon} size={30} />
        </View>
      ) : null}
      <Text variant="heading" align="center">{title}</Text>
      {message ? <Text tone="muted" align="center">{message}</Text> : null}
      {action ? <View style={{ marginTop: theme.space.md }}>{action}</View> : null}
    </View>
  );
}

export function ErrorState({ message, onRetry, title = "Something went wrong" }: { message: string; onRetry?: () => void; title?: string }) {
  const theme = useTheme();
  return (
    <View accessibilityRole="alert" style={{ flex: 1, minHeight: 200, alignItems: "center", justifyContent: "center", padding: theme.space.xl, gap: theme.space.sm }}>
      <Text variant="heading" align="center">{title}</Text>
      <Text tone="muted" align="center">{message}</Text>
      {onRetry ? <View style={{ marginTop: theme.space.md }}><Button variant="outline" onPress={onRetry}>Try again</Button></View> : null}
    </View>
  );
}
