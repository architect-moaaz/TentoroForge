import { Inter_400Regular, Inter_500Medium, Inter_600SemiBold, Inter_700Bold, useFonts } from '@expo-google-fonts/inter';
import { PlusJakartaSans_700Bold } from '@expo-google-fonts/plus-jakarta-sans';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { ActivityIndicator, View } from 'react-native';

import { OrgProvider } from '@/lib/org';
import { SessionProvider, useSession } from '@/lib/session';
import { font, useColors } from '@/theme';
import { ThemePrefProvider, useThemePref } from '@/theme-pref';

// Signed-in people see the app screens; signed-out people see only login.
// `Stack.Protected` swaps them as soon as the session status changes.
function Gate() {
  const { status } = useSession();
  const { ready } = useThemePref();
  const colors = useColors();
  const [fontsLoaded] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
    PlusJakartaSans_700Bold,
  });

  if (status === 'loading' || !fontsLoaded || !ready) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.background }}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <>
      <StatusBar style={colors.statusBar} />
      <Stack
        screenOptions={{
          // Pages slide in from the right on both phones; swipe back works on iOS.
          animation: 'slide_from_right',
          gestureEnabled: true,
          headerStyle: { backgroundColor: colors.surfaceSecondary },
          headerShadowVisible: false,
          headerTintColor: colors.text,
          headerTitleStyle: { fontFamily: font.display, fontSize: 18, color: colors.text },
          contentStyle: { backgroundColor: colors.surfaceSecondary },
        }}>
        <Stack.Protected guard={status === 'in'}>
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="s/[key]" options={{ title: '', headerBackTitle: 'Menu' }} />
          <Stack.Screen name="project/[id]" options={{ title: 'Smith', headerBackTitle: 'Back' }} />
        </Stack.Protected>
        <Stack.Protected guard={status === 'out'}>
          <Stack.Screen name="login" options={{ headerShown: false }} />
          <Stack.Screen name="signup" options={{ headerShown: false, animation: 'slide_from_bottom' }} />
        </Stack.Protected>
      </Stack>
    </>
  );
}

export default function RootLayout() {
  return (
    <ThemePrefProvider>
      <SessionProvider>
        <OrgProvider>
          <Gate />
        </OrgProvider>
      </SessionProvider>
    </ThemePrefProvider>
  );
}
