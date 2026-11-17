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
import { ROLE_TABS, TABS } from "@/navigation.generated";
import { useSession } from "@/sdk";
import { theme } from "@/theme";

export default function TabsLayout() {
  // EACH ROLE HAS ITS OWN BAR where the roles differ (`ROLE_TABS`): the bar declares every role's tabs and shows
  // the signed-in person's own, in their order. Everyone else's tabs stay out of the bar (`href: null`) but their
  // screens are still reachable by route. With one shared bar `ROLE_TABS` is empty and nothing changes.
  const { user } = useSession();
  const role = String((user as { role?: unknown } | null)?.role ?? "");
  const mine = ROLE_TABS[role];
  const shown = mine ? mine.map((name) => TABS.find((t) => t.name === name)).filter((t): t is (typeof TABS)[number] => !!t) : TABS;
  const hidden = TABS.filter((t) => !shown.some((s) => s.name === t.name));
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
      {shown.map((tab) => (
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
      {hidden.map((tab) => (
        <Tabs.Screen key={tab.name} name={tab.name} options={{ href: null }} />
      ))}
    </Tabs>
  );
}
