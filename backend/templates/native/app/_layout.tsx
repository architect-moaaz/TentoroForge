// The root of the app — fixed, the same in every app. It mounts what every
// screen needs (safe areas, the net under a crashing screen, the session, the
// toasts) and keeps the person on the right side of the sign-in: signed out goes
// to /login, signed in leaves it, an organisation to choose goes to the picker.
// The rule itself is `gateDecision` (src/sdk/gate.ts).
//
// The navigator is ALWAYS mounted (expo-router refuses a redirect before it
// is); while the saved session is being checked, or the app cannot be reached,
// a cover is drawn over it instead.

import * as React from "react";
import { View } from "react-native";
import { Stack, usePathname, useRouter, type Href } from "expo-router";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { useFonts } from "expo-font";
import { ErrorBoundary, ErrorState, Loading } from "@/ui";
import { SessionProvider, ToastProvider, appConfigured, useOrganisations, useSession } from "@/sdk";
import { gateDecision } from "@/sdk/gate";
import { HOME, PUBLIC_ROUTES } from "@/config.generated";
import { FONT_FILES } from "@/fonts.generated";
import { theme } from "@/theme";

function Gate() {
  const { status, refresh } = useSession();
  const { needsOrganisation } = useOrganisations();
  const pathname = usePathname();
  const router = useRouter();

  React.useEffect(() => {
    const to = gateDecision({ status, needsOrganisation, pathname, publicRoutes: PUBLIC_ROUTES, home: HOME });
    if (to) router.replace(to as Href);
  }, [status, needsOrganisation, pathname, router]);

  const cover = !appConfigured
    ? <ErrorState title="Not connected yet" message="This app does not know where its server is. Set EXPO_PUBLIC_APP_URL (or extra.appUrl in app.json) to the deployed address and rebuild." />
    : status === "loading" ? <Loading />
    : status === "offline" ? <ErrorState title="Cannot reach the app" message="Check your connection. You stay signed in." onRetry={() => { void refresh(); }} />
    : null;

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.background }}>
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: theme.colors.background } }} />
      {cover ? <View style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: theme.colors.background }}>{cover}</View> : null}
    </View>
  );
}

export default function RootLayout() {
  // The app's typefaces (`fonts.generated.ts`) are loaded before anything is drawn in them. A face that
  // fails to load is not a failure of the app: the text falls back to the system font.
  const [loaded, failed] = useFonts(FONT_FILES);
  if (!loaded && !failed) return <View style={{ flex: 1, backgroundColor: theme.colors.background }} />;
  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <SessionProvider>
          <ToastProvider>
            <Gate />
          </ToastProvider>
        </SessionProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}
