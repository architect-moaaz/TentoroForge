// The app SDK (native) — toasts. The web uses `sonner`'s `toast.success(...)`;
// this is the same call with no dependency: `toast` works from anywhere (a
// hook, a handler, a plain function) because it only emits an event, and the
// `ToastProvider` the root layout mounts is what draws it, at the top of the
// screen under the status bar, away from the keyboard.
//
//   toast.success("Saved");
//   toast.error("Could not save", { description: "The amount must be positive." });
//
// `useWorkflow` toasts for the screen (the refusal's own sentence, "<Name>
// failed", "<Name> — done"), so a screen rarely calls this itself.

import * as React from "react";
import { Animated, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { toasts, type ToastKind, type ToastMessage } from "./events";
import { useTheme } from "../theme";

let nextId = 1;
const send = (kind: ToastKind, title: string, description?: string) => toasts.emit({ id: nextId++, kind, title, description });

export const toast = {
  success: (title: string, opts?: { description?: string }) => send("success", title, opts?.description),
  error: (title: string, opts?: { description?: string }) => send("error", title, opts?.description),
  info: (title: string, opts?: { description?: string }) => send("info", title, opts?.description),
};

/** The same object, from a hook, for a component that prefers one. */
export function useToast(): typeof toast {
  return toast;
}

const SHOWN = 3;

/** How long a toast stays: an error is read twice. */
const lifetime = (kind: ToastKind) => (kind === "error" ? 6000 : 3500);

function ToastCard({ message, onDone }: { message: ToastMessage; onDone: (id: number) => void }) {
  const theme = useTheme();
  const fade = React.useRef(new Animated.Value(0)).current;
  React.useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 160, useNativeDriver: true }).start();
    const t = setTimeout(() => onDone(message.id), lifetime(message.kind));
    return () => clearTimeout(t);
  }, [fade, message.id, message.kind, onDone]);
  const c = theme.colors;
  const tone = message.kind === "error"
    ? { bg: c.destructive, fg: c.destructiveForeground }
    : message.kind === "success"
      ? { bg: c.success, fg: c.successForeground }
      : { bg: c.inverse, fg: c.inverseForeground };
  return (
    <Animated.View style={{ opacity: fade }}>
      <Pressable
        onPress={() => onDone(message.id)}
        accessibilityRole="alert"
        accessibilityLiveRegion="polite"
        accessibilityLabel={message.description ? `${message.title}. ${message.description}` : message.title}
        style={[styles.card, { backgroundColor: tone.bg, borderRadius: theme.radius + 4 }]}>
        <Text style={[styles.title, { color: tone.fg }]}>{message.title}</Text>
        {message.description ? <Text style={[styles.body, { color: tone.fg }]}>{message.description}</Text> : null}
      </Pressable>
    </Animated.View>
  );
}

/** Mount once, near the root; draws what `toast.*` emits. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const insets = useSafeAreaInsets();
  const [list, setList] = React.useState<ToastMessage[]>([]);
  React.useEffect(() => toasts.subscribe((m) => setList((cur) => [...cur, m].slice(-SHOWN))), []);
  const dismiss = React.useCallback((id: number) => setList((cur) => cur.filter((m) => m.id !== id)), []);
  return (
    <View style={styles.fill}>
      {children}
      <View pointerEvents="box-none" style={[styles.host, { top: insets.top + 8 }]}>
        {list.map((m) => <ToastCard key={m.id} message={m} onDone={dismiss} />)}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  host: { position: "absolute", left: 16, right: 16, gap: 8, zIndex: 1000 },
  card: { paddingHorizontal: 16, paddingVertical: 12, minHeight: 44, justifyContent: "center" },
  title: { fontSize: 15, fontWeight: "600" },
  body: { fontSize: 13, marginTop: 2, opacity: 0.92 },
});
