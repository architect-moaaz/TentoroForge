// The component kit - the hamburger menu. When the Blueprint says a phone navigates by `drawer`
// (`navigation.mobile`), the app has no bottom tab bar: every main page is an item of this menu, opened by the
// hamburger at the left of a main page's header, and the page you are on is marked. It is made of React Native's
// own Modal and Animated, so it needs no native module of its own.
//
// The items are `MENU` in `src/navigation.generated.ts` (the Blueprint's main pages, in its navigation's order,
// then Account when the app has a sign-in). A screen never draws this: `Header` (in `Screen`) places the button on
// a main page, and a page that is opened from another one keeps its back arrow.

import * as React from "react";
import { Animated, Dimensions, Easing, Modal, Pressable, ScrollView, View } from "react-native";
import { useRouter, usePathname, type Href } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTheme } from "../theme";
import { Icon, type IconName } from "./Icon";
import { Text } from "./Text";
import { APP_NAME } from "../config.generated";
import { MENU } from "../navigation.generated";

const norm = (path: string) => path.replace(/\/+$/, "") || "/";

/** Whether this address is one of the menu's pages: a main page shows the hamburger, anything else a back arrow. */
export function isMenuRoute(pathname: string): boolean {
  return MENU.some((m) => norm(m.route) === norm(pathname));
}

/** The panel and its scrim. */
export function AppMenu({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const theme = useTheme();
  const router = useRouter();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const width = Math.min(Dimensions.get("window").width * 0.8, 340);
  const slide = React.useRef(new Animated.Value(-width)).current;
  const fade = React.useRef(new Animated.Value(0)).current;
  const [mounted, setMounted] = React.useState(visible);

  React.useEffect(() => {
    if (visible) {
      setMounted(true);
      Animated.parallel([
        Animated.timing(slide, { toValue: 0, duration: 220, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
        Animated.timing(fade, { toValue: 1, duration: 220, useNativeDriver: true }),
      ]).start();
    } else if (mounted) {
      Animated.parallel([
        Animated.timing(slide, { toValue: -width, duration: 180, easing: Easing.in(Easing.cubic), useNativeDriver: true }),
        Animated.timing(fade, { toValue: 0, duration: 180, useNativeDriver: true }),
      ]).start(() => setMounted(false));
    }
  }, [visible, mounted, slide, fade, width]);

  const go = (route: string) => {
    onClose();
    if (norm(route) !== norm(pathname)) router.replace(route as Href);
  };

  const letter = (APP_NAME.trim()[0] ?? "A").toUpperCase();
  return (
    <Modal visible={mounted} transparent animationType="none" onRequestClose={onClose} statusBarTranslucent>
      <View style={{ flex: 1 }}>
        <Animated.View style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, opacity: fade, backgroundColor: theme.alpha("inverse", 0.45) }}>
          <Pressable accessibilityRole="button" accessibilityLabel="Close menu" onPress={onClose} style={{ flex: 1 }} />
        </Animated.View>
        <Animated.View
          accessibilityViewIsModal
          style={[{
            position: "absolute", top: 0, bottom: 0, left: 0, width, transform: [{ translateX: slide }],
            backgroundColor: theme.colors.card, paddingTop: insets.top + theme.space.lg, paddingBottom: insets.bottom + theme.space.lg,
            borderTopRightRadius: theme.radii.lg, borderBottomRightRadius: theme.radii.lg,
          }, theme.shadow(3)]}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.md, paddingHorizontal: theme.pagePadding, paddingBottom: theme.space.lg }}>
            <View style={{ width: 44, height: 44, borderRadius: theme.radii.md, alignItems: "center", justifyContent: "center", backgroundColor: theme.colors.primary }}>
              <Text variant="heading" style={{ color: theme.colors.primaryForeground }}>{letter}</Text>
            </View>
            <Text variant="heading" numberOfLines={1} style={{ flex: 1 }}>{APP_NAME}</Text>
          </View>
          <ScrollView contentContainerStyle={{ paddingHorizontal: theme.space.sm, gap: theme.space.xs }}>
            {MENU.map((item) => {
              const active = norm(item.route) === norm(pathname);
              return (
                <Pressable
                  key={item.route}
                  onPress={() => go(item.route)}
                  accessibilityRole="menuitem"
                  accessibilityState={{ selected: active }}
                  accessibilityLabel={item.title}
                  style={{
                    flexDirection: "row", alignItems: "center", gap: theme.space.md, minHeight: theme.touch,
                    paddingHorizontal: theme.space.md, borderRadius: theme.radii.md,
                    backgroundColor: active ? theme.alpha("primary", 0.1) : "transparent",
                  }}
                >
                  <Icon name={item.icon as IconName} size={22} tone={active ? "primary" : "muted"} />
                  <Text weight={active ? "semibold" : "medium"} tone={active ? "primary" : "default"} numberOfLines={1} style={{ flex: 1 }}>{item.title}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </Animated.View>
      </View>
    </Modal>
  );
}

/** The hamburger: opens the menu. */
export function MenuButton() {
  const theme = useTheme();
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Pressable
        onPress={() => setOpen(true)}
        accessibilityRole="button"
        accessibilityLabel="Open menu"
        hitSlop={8}
        style={{ width: theme.touch, height: theme.touch, marginLeft: -theme.space.sm, alignItems: "center", justifyContent: "center" }}
      >
        <Icon name="menu" size={26} />
      </Pressable>
      <AppMenu visible={open} onClose={() => setOpen(false)} />
    </>
  );
}
