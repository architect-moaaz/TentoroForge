/**
 * Mobile shell for __APP_NAME__.
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
  StatusBar,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView, SafeAreaProvider } from "react-native-safe-area-context";
import { WebView, WebViewNavigation } from "react-native-webview";
import { CameraView, useCameraPermissions } from "expo-camera";
import { Modal, Pressable } from "react-native";
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

  // Auto-retry when the web app is momentarily unreachable (dev-server
  // restart, Wi-Fi blip): the WebView error page is terminal otherwise.
  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => webRef.current?.reload(), 3000);
    return () => clearTimeout(t);
  }, [error]);

  const webRef = useRef<WebView>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [camPermission, requestCamPermission] = useCameraPermissions();

  // The in-page camera (getUserMedia inside the WebView) only works when the
  // APP holds Android's runtime CAMERA permission — the WebView's auto-grant
  // covers the web layer, not the OS layer. Ask once at startup so "Start
  // Camera" on any page just works.
  useEffect(() => {
    if (camPermission && !camPermission.granted && camPermission.canAskAgain) {
      void requestCamPermission();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camPermission?.granted]);
  const scannedRef = useRef(false);

  const openScanner = useCallback(async () => {
    if (!camPermission?.granted) {
      const res = await requestCamPermission();
      if (!res.granted) return;
    }
    scannedRef.current = false;
    setScannerOpen(true);
  }, [camPermission, requestCamPermission]);

  const onBarcodeScanned = useCallback(({ data }: { data: string }) => {
    if (scannedRef.current || !data) return;
    scannedRef.current = true;
    setScannerOpen(false);
    // Hand the decoded value to the page's BarcodeScanner component.
    webRef.current?.injectJavaScript(
      `window.dispatchEvent(new CustomEvent('forge-barcode',{detail:${JSON.stringify(
        data
      )}}));true;`
    );
  }, []);
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
        {/* No ScrollView wrapper: nesting the WebView inside one breaks
          * Android's video-surface composition (black camera preview). The
          * WebView's own pullToRefreshEnabled covers pull-to-refresh. */}
        <View style={styles.container}>
          <WebView
            ref={webRef}
            source={{ uri: APP_URL }}
            originWhitelist={["*"]}
            onLoadStart={() => {
              setLoading(true);
              setError(null);
            }}
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
            allowsInlineMediaPlayback
            mediaPlaybackRequiresUserAction={false}
            mediaCapturePermissionGrantType="grant"
            onMessage={() => {}}
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
          <Pressable style={styles.scanFab} onPress={openScanner}>
            <Text style={styles.scanFabText}>▦ Scan</Text>
          </Pressable>
          <Modal
            visible={scannerOpen}
            animationType="slide"
            onRequestClose={() => setScannerOpen(false)}
          >
            <View style={styles.scannerContainer}>
              <CameraView
                style={styles.camera}
                facing="back"
                barcodeScannerSettings={{
                  barcodeTypes: [
                    "ean13",
                    "ean8",
                    "upc_a",
                    "upc_e",
                    "code128",
                    "code39",
                    "qr",
                  ],
                }}
                onBarcodeScanned={onBarcodeScanned}
              />
              <View style={styles.reticle} pointerEvents="none" />
              <Pressable
                style={styles.closeScanner}
                onPress={() => setScannerOpen(false)}
              >
                <Text style={styles.closeScannerText}>Cancel</Text>
              </Pressable>
            </View>
          </Modal>
          {error && (
            <View style={styles.centered}>
              <Text style={styles.title}>Couldn&apos;t load</Text>
              <Text style={styles.body}>{error}</Text>
              <Text style={styles.body}>Retrying automatically…</Text>
              <Pressable
                style={styles.retryBtn}
                onPress={() => {
                  setError(null);
                  webRef.current?.reload();
                }}
              >
                <Text style={styles.retryBtnText}>Retry now</Text>
              </Pressable>
            </View>
          )}
        </View>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  retryBtn: {
    marginTop: 16,
    backgroundColor: "#6D28D9",
    paddingHorizontal: 24,
    paddingVertical: 10,
    borderRadius: 8,
  },
  retryBtnText: {
    color: "#fff",
    fontWeight: "600",
    fontSize: 15,
  },
  scanFab: {
    position: "absolute",
    bottom: 28,
    right: 20,
    backgroundColor: "#7c3aed",
    paddingHorizontal: 22,
    paddingVertical: 14,
    borderRadius: 28,
    elevation: 6,
    shadowColor: "#000",
    shadowOpacity: 0.3,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
  },
  scanFabText: { color: "#fff", fontWeight: "700", fontSize: 16 },
  scannerContainer: { flex: 1, backgroundColor: "#000" },
  camera: { flex: 1 },
  reticle: {
    position: "absolute",
    top: "30%",
    left: "12%",
    right: "12%",
    height: "25%",
    borderWidth: 2,
    borderColor: "rgba(255,255,255,0.85)",
    borderRadius: 12,
  },
  closeScanner: {
    position: "absolute",
    bottom: 48,
    alignSelf: "center",
    backgroundColor: "rgba(255,255,255,0.15)",
    paddingHorizontal: 28,
    paddingVertical: 12,
    borderRadius: 24,
  },
  closeScannerText: { color: "#fff", fontSize: 16, fontWeight: "600" },
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
