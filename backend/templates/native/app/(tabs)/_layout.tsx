// The bottom tab bar — the application's MAIN pages, one tab each. Fixed code,
// shipped into an app only when the Blueprint has tabs to show: the tabs
// themselves are `TABS` in `src/navigation.generated.ts` (chosen from the
// Blueprint's navigation by `native_projection.tab_pages`), and each tab's
// screen is a route file in this folder.
//
// WHY TABS AND NOT A DRAWER: a phone's thumb reaches the bottom edge, both
// platforms teach people to look there, and the main destinations of a small
// application (two to five) fit. Pages that are not destinations — a form to
// add, one record opened from a list — are stacked ABOVE the tabs, so the bar
// stays put underneath and `back` returns to it.

import * as React from "react";
import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { TABS } from "@/navigation.generated";
import { theme } from "@/theme";

export default function TabsLayout() {
  return (
    <Tabs
      sceneContainerStyle={{ backgroundColor: theme.colors.background }}
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.colors.primary,
        tabBarInactiveTintColor: theme.colors.mutedForeground,
        tabBarStyle: { backgroundColor: theme.colors.card, borderTopColor: theme.colors.border },
        tabBarLabelStyle: { fontSize: 12, fontWeight: "600" },
      }}
    >
      {TABS.map((tab) => (
        <Tabs.Screen
          key={tab.name}
          name={tab.name}
          options={{
            title: tab.title,
            tabBarAccessibilityLabel: tab.title,
            tabBarIcon: ({ color, size }) => <Ionicons name={tab.icon as keyof typeof Ionicons.glyphMap} size={size} color={color} />,
          }}
        />
      ))}
    </Tabs>
  );
}
