import { Feather } from '@expo/vector-icons';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { EmptyState } from '@/components/kit';
import { Button } from '@/components/ui';
import { apiJson } from '@/lib/api';
import { API_BASE } from '@/lib/config';
import { icon, radius, shadow, space, type, useColors, type Palette } from '@/theme';

const STATUS_POLL_MS = 3000;
const START_LIMIT_MS = 4 * 60 * 1000;

const formatWait = (s: number) => `Waiting ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

interface PreviewInfo {
  running?: boolean;
  port: number | null;
  servePath?: string;
  serveUrl?: string;
}

/** Where to open the preview. The server names the address it will serve the app at
 *  (`serveUrl`); use it when it is a real address. On a developer machine it says
 *  `localhost`, which on a phone is the phone itself, so fall back to the server we talk to. */
function addressOf(info: PreviewInfo): string {
  const path = info.servePath ?? '';
  try {
    const host = info.serveUrl ? new URL(info.serveUrl).hostname : '';
    if (host && !['localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]'].includes(host)) return info.serveUrl as string;
  } catch {
    /* a malformed address: use the fallback */
  }
  return path.startsWith('http') ? path : `${API_BASE}${path}`;
}

/** The generated app, shown in a WebView (a small browser inside the app).
 *  `reloadKey` going up means Smith changed the app, so the page reloads. */
export function PreviewView({ projectId, reloadKey }: { projectId: string; reloadKey: number }) {
  const [uri, setUri] = useState<string | null>(null);
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Our own reload count, added to Smith's, for the toolbar's reload button.
  const [manualKey, setManualKey] = useState(0);
  // Phone layout by default; the toolbar switches to the desktop layout.
  const [desktop, setDesktop] = useState(false);
  const [pageLoading, setPageLoading] = useState(true);
  // How wide the page thinks the screen is, so you can see which layout it chose.
  const [pageWidth, setPageWidth] = useState<number | null>(null);

  const [waited, setWaited] = useState(0);
  const attempt = useRef<AbortController | null>(null);

  // The server answers /preview/start only once the app has compiled, which can
  // take minutes the first time. So while that call waits, we also ask
  // /preview/status every few seconds and take whichever says "running" first,
  // and give up with a clear message after START_LIMIT_MS.
  const start = useCallback(async () => {
    attempt.current?.abort();
    const ctl = new AbortController();
    attempt.current = ctl;
    setLoading(true);
    setError(null);
    setWaited(0);
    const base = `/api/projects/${projectId}/preview`;
    const open = (address: string) => setUri(address);

    try {
      const status = await apiJson<PreviewInfo>(`${base}/status`, { signal: ctl.signal });
      if (status.running && status.servePath) {
        open(addressOf(status));
        return;
      }

      const servePath = await new Promise<string>((resolve, reject) => {
        const stop = () => {
          clearInterval(poll);
          clearTimeout(limit);
        };
        const poll = setInterval(async () => {
          try {
            const s = await apiJson<PreviewInfo>(`${base}/status`, { signal: ctl.signal });
            if (s.running && s.servePath) {
              stop();
              resolve(addressOf(s));
            }
          } catch {
            /* a missed poll is fine; the next one tries again */
          }
        }, STATUS_POLL_MS);
        const limit = setTimeout(() => {
          stop();
          ctl.abort();
          reject(new Error('The preview took too long to start. The server may still be building it, so try again in a minute.'));
        }, START_LIMIT_MS);
        ctl.signal.addEventListener('abort', stop);

        apiJson<PreviewInfo>(`${base}/start`, { method: 'POST', signal: ctl.signal })
          .then((r) => {
            stop();
            if (r.servePath) resolve(addressOf(r));
            else reject(new Error('The preview has no address yet. Build the app first.'));
          })
          .catch((e) => {
            // Aborted by the time limit or by leaving: the limit's message (or nothing) wins.
            if (ctl.signal.aborted) return;
            stop();
            reject(e);
          });
      });
      if (!ctl.signal.aborted) open(servePath);
    } catch (e) {
      if (attempt.current === ctl) setError(e instanceof Error ? e.message : 'Could not start the preview');
    } finally {
      if (attempt.current === ctl) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    start();
    return () => attempt.current?.abort();
  }, [start]);

  // A seconds counter so a long first start does not look frozen.
  useEffect(() => {
    if (!loading) return;
    const t = setInterval(() => setWaited((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [loading]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brand} />
        <Text style={styles.title}>Starting the preview…</Text>
        <Text style={styles.note}>
          {waited < 8
            ? 'Waking up your app.'
            : `The first start builds the app from scratch and can take up to 3 minutes. ${formatWait(waited)}`}
        </Text>
        {waited >= 8 ? <Button label="Cancel" tone="outline" onPress={() => {
          attempt.current?.abort();
          setLoading(false);
          setError('Stopped waiting. The server may still finish building, so try again soon.');
        }} /> : null}
      </View>
    );
  }

  if (error || !uri) {
    return (
      <EmptyState
        icon="eye-off"
        title="No preview yet"
        text={error ?? 'Nothing to show'}
        action={{ label: 'Try again', onPress: start }}
      />
    );
  }

  return (
    <View style={styles.wrap}>
      <View style={styles.bar}>
        <View style={[styles.dot, { backgroundColor: pageLoading ? '#f59e0b' : colors.success }]} />
        <Text style={styles.address} numberOfLines={1}>
          {uri.replace(/^https?:\/\//, '')}
        </Text>
        {pageWidth ? <Text style={styles.widthChip}>{pageWidth}px</Text> : null}
        <Pressable
          onPress={() => {
            setPageWidth(null);
            setDesktop((d) => !d);
          }}
          hitSlop={10}
          accessibilityLabel={desktop ? 'Show phone layout' : 'Show desktop layout'}
          accessibilityState={{ selected: desktop }}
          style={[styles.barBtn, desktop && { backgroundColor: colors.brandSoft }]}>
          <Feather name={desktop ? 'monitor' : 'smartphone'} size={icon.sm + 1} color={desktop ? colors.brand : colors.text} />
        </Pressable>
        <Pressable onPress={() => setManualKey((k) => k + 1)} hitSlop={10} accessibilityLabel="Reload preview" style={styles.barBtn}>
          <Feather name="rotate-cw" size={icon.sm + 1} color={colors.text} />
        </Pressable>
        <Pressable onPress={() => WebBrowser.openBrowserAsync(uri)} hitSlop={10} accessibilityLabel="Open in browser" style={styles.barBtn}>
          <Feather name="external-link" size={icon.sm + 1} color={colors.text} />
        </Pressable>
      </View>

      <PreviewFrame
        uri={uri}
        reloadKey={`${reloadKey}-${manualKey}`}
        onLoading={setPageLoading}
        onWidth={setPageWidth}
        styles={styles}
        desktop={desktop}
      />
    </View>
  );
}

// The relay waits 30 seconds for the app's own server. A page opened for the
// first time can take longer to compile, and the relay then answers 502/504.
// The compile keeps going on the server, so a short wait and a reload usually works.
const AUTO_RETRIES = 3;
const RETRY_DELAY_MS = 4000;

// Desktop mode: say we are a desktop browser, and show the app in a frame 1280px wide
// that shrinks to fit the phone (pinch to zoom in). Setting the viewport tag did not work on iPhone.
const DESKTOP_WIDTH = 1280;
const DESKTOP_UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const desktopShell = (uri: string) => `<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>html,body{margin:0;height:100%;overflow:hidden;background:#fff}iframe{border:0;width:${DESKTOP_WIDTH}px;transform-origin:0 0}</style>
</head><body><iframe id="f" src="${uri.replace(/"/g, '%22')}"></iframe>
<script>
function fit(){var s=window.innerWidth/${DESKTOP_WIDTH},f=document.getElementById('f');f.style.transform='scale('+s+')';f.style.height=(window.innerHeight/s)+'px';}
fit();addEventListener('resize',fit);
window.ReactNativeWebView&&window.ReactNativeWebView.postMessage(JSON.stringify({width:${DESKTOP_WIDTH}}));
</script></body></html>`;

// Tells the toolbar how wide the page believes the screen is (CSS pixels). The app
// switches to its desktop layout at 768 and 1024, so this number shows which one it got.
const REPORT_WIDTH_JS = `(function () {
  function tell() {
    window.ReactNativeWebView && window.ReactNativeWebView.postMessage(JSON.stringify({ width: window.innerWidth }));
  }
  tell();
  window.addEventListener('resize', tell);
  window.addEventListener('load', function () { setTimeout(tell, 300); });
})(); true;`;

/** The WebView, plus a quiet reload when the relay timed out on a page that was still compiling. */
function PreviewFrame({
  uri,
  reloadKey,
  onLoading,
  onWidth,
  styles,
  desktop = false,
}: {
  uri: string;
  reloadKey: string;
  onLoading: (loading: boolean) => void;
  onWidth: (width: number) => void;
  styles: ReturnType<typeof makeStyles>;
  desktop?: boolean;
}) {
  const colors = useColors();
  const [tries, setTries] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [pageLoading, setPageLoading] = useState(true);
  // A new reloadKey (Smith changed the app, or the reload button) gets a fresh set of tries.
  const [seenKey, setSeenKey] = useState(reloadKey);
  if (seenKey !== reloadKey) {
    setSeenKey(reloadKey);
    setTries(0);
    setRetrying(false);
  }

  useEffect(() => {
    if (!retrying) return;
    const t = setTimeout(() => {
      setTries((n) => n + 1);
      setRetrying(false);
    }, RETRY_DELAY_MS);
    return () => clearTimeout(t);
  }, [retrying]);

  const busy = pageLoading || retrying;

  return (
    <View style={styles.frame}>
      {/* A new `key` remounts the WebView, which reloads the page. */}
      <WebView
        key={`${reloadKey}-${tries}-${desktop ? 'd' : 'm'}`}
        // Desktop: a page that is itself 1280 wide holds the app in a frame, shrunk to fit.
        // The frame's width decides the layout, which a phone's viewport tag cannot be made to do.
        source={desktop ? { html: desktopShell(uri), baseUrl: API_BASE } : { uri }}
        style={{ flex: 1 }}
        userAgent={desktop ? DESKTOP_UA : undefined}
        injectedJavaScript={desktop ? undefined : REPORT_WIDTH_JS}
        onMessage={(e) => {
          try {
            const w = Number(JSON.parse(e.nativeEvent.data)?.width);
            if (w > 0) onWidth(w);
          } catch {
            /* not our message */
          }
        }}
        scalesPageToFit
        setBuiltInZoomControls
        setDisplayZoomControls={false}
        onLoadStart={() => {
          setPageLoading(true);
          onLoading(true);
        }}
        onLoadEnd={() => {
          setPageLoading(false);
          onLoading(false);
        }}
        onHttpError={(e) => {
          const code = e.nativeEvent.statusCode;
          if ((code === 502 || code === 504) && tries < AUTO_RETRIES) setRetrying(true);
        }}
      />
      {busy ? (
        <View style={styles.loadingOverlay} pointerEvents="none">
          <ActivityIndicator color={colors.brand} />
          {retrying || tries > 0 ? (
            <Text style={styles.note}>
              Still building this page… trying again ({Math.min(tries + 1, AUTO_RETRIES)}/{AUTO_RETRIES})
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    wrap: { flex: 1, backgroundColor: colors.surfaceSecondary, paddingHorizontal: space.md, paddingBottom: space.md, gap: space.sm },
    center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: space.xxl, gap: space.md, backgroundColor: colors.surfaceSecondary },
    title: { ...type.headline, color: colors.text, textAlign: 'center' },
    note: { ...type.callout, color: colors.textSecondary, textAlign: 'center', maxWidth: 300 },
    bar: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.sm,
      height: 40,
      paddingLeft: space.md + 2,
      paddingRight: space.xs,
      borderRadius: radius.pill,
      backgroundColor: colors.muted,
    },
    dot: { width: 8, height: 8, borderRadius: 4 },
    address: { flex: 1, ...type.caption, color: colors.textSecondary },
    widthChip: { ...type.caption, color: colors.textSecondary, fontVariant: ['tabular-nums'] },
    barBtn: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
    frame: {
      flex: 1,
      borderRadius: radius.xxl,
      overflow: 'hidden',
      backgroundColor: colors.surface,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: colors.border,
      ...shadow.card,
    },
    loadingOverlay: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center', gap: space.md, padding: space.xl, backgroundColor: colors.surface },
  });
