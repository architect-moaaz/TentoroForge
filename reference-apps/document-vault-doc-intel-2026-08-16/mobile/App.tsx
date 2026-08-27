/**
 * Mobile shell for 9y8de8i7.
 *
 * A full-screen React Native app that hosts the deployed Next.js web
 * app inside a WebView. Native chrome (status bar, safe area, back
 * gesture, deep links) is handled by RN so users get the "installed
 * app" feel even though the UI is served from `EXPO_PUBLIC_APP_URL`.
 *
 * Configuration comes from app.json's `expo.extra.appUrl`, which the
 * generator writes at scaffold time. Override at build time with
 * `EAS_BUILD_PROFILE=preview eas build --platform ... --profile preview
 * --env EXPO_PUBLIC_APP_URL=<uat url>` to point a preview APK at UAT.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  BackHandler,
  Linking,
  Platform,
  RefreshControl,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView, SafeAreaProvider } from "react-native-safe-area-context";
import { WebView, WebViewNavigation } from "react-native-webview";
import Constants from "expo-constants";

const APP_URL: string =
  (process.env.EXPO_PUBLIC_APP_URL as string | undefined) ??
  (Constants.expoConfig?.extra?.appUrl as string | undefined) ??
  "";
const APP_NAME: string =
  (Constants.expoConfig?.extra?.appName as string | undefined) ??
  Constants.expoConfig?.name ??
  "App";

/**
 * URLs that should open in the system browser rather than inside the
 * WebView — anything outside our app's origin.
 */
function isExternal(url: string): boolean {
  if (!APP_URL) return false;
  try {
    const base = new URL(APP_URL).origin;
    return !url.startsWith(base);
  } catch {
    return false;
  }
}

function MissingConfig(): JSX.Element {
  return (
    <View style={styles.centered}>
      <Text style={styles.title}>{APP_NAME}</Text>
      <Text style={styles.body}>
        This app isn&apos;t configured yet — the platform hasn&apos;t
        pointed it at a deployed URL. Ask your admin to complete the
        deploy step, then reopen this app.
      </Text>
    </View>
  );
}

export default function App(): JSX.Element {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const webRef = useRef<WebView>(null);
  const canGoBackRef = useRef(false);

  // Wire the hardware/gesture back button on Android to WebView history.
  // On iOS, users use a swipe-from-edge gesture handled below.
  useEffect(() => {
    if (Platform.OS !== "android") return;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      if (canGoBackRef.current && webRef.current) {
        webRef.current.goBack();
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, []);

  const onNavStateChange = useCallback((state: WebViewNavigation) => {
    canGoBackRef.current = state.canGoBack;
  }, []);

  const onShouldStartLoadWithRequest = useCallback((req: { url: string }) => {
    if (isExternal(req.url)) {
      void Linking.openURL(req.url);
      return false;
    }
    return true;
  }, []);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    webRef.current?.reload();
    // Refresh spinner clears when the WebView fires onLoadEnd.
  }, []);

  if (!APP_URL) return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="default" />
        <MissingConfig />
      </SafeAreaView>
    </SafeAreaProvider>
  );

  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="default" />
        <ScrollView
          style={styles.container}
          contentContainerStyle={styles.container}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
        >
          <WebView
            ref={webRef}
            source={{ uri: APP_URL }}
            originWhitelist={["*"]}
            onLoadStart={() => setLoading(true)}
            onLoadEnd={() => {
              setLoading(false);
              setRefreshing(false);
            }}
            onError={(e) => {
              setError(e.nativeEvent.description);
              setLoading(false);
              setRefreshing(false);
            }}
            onNavigationStateChange={onNavStateChange}
            onShouldStartLoadWithRequest={onShouldStartLoadWithRequest}
            javaScriptEnabled
            domStorageEnabled
            sharedCookiesEnabled
            allowsBackForwardNavigationGestures
            pullToRefreshEnabled
            startInLoadingState
            renderLoading={() => (
              <View style={styles.centered}>
                <ActivityIndicator size="large" />
              </View>
            )}
            style={styles.webview}
          />
          {loading && !refreshing && (
            <View style={styles.overlay} pointerEvents="none">
              <ActivityIndicator size="large" />
            </View>
          )}
          {error && (
            <View style={styles.centered}>
              <Text style={styles.title}>Couldn&apos;t load</Text>
              <Text style={styles.body}>{error}</Text>
            </View>
          )}
        </ScrollView>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#ffffff",
  },
  webview: {
    flex: 1,
  },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
  },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  title: {
    fontSize: 20,
    fontWeight: "600",
    marginBottom: 8,
    textAlign: "center",
  },
  body: {
    fontSize: 14,
    color: "#555",
    textAlign: "center",
    lineHeight: 20,
  },
});
