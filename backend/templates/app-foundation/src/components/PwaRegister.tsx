"use client";
// The application on a phone: registers the service worker that keeps the
// shell (so the app opens from the home screen, and offline), keeps the
// browser's install prompt for the frame's Install button, and — when the
// application sends push — subscribes a device once the person asks.
import { apiPath } from "@/lib/api-path";
import { MOBILE } from "@/lib/mobile";
import * as React from "react";

type InstallPrompt = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");

/** Standalone: opened from the home screen, not in a browser tab. */
export function isInstalled(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
}

export function isIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  return /iPad|iPhone|iPod/.test(navigator.userAgent) && !("MSStream" in window);
}

let deferred: InstallPrompt | null = null;
const listeners = new Set<() => void>();

export function PwaRegister() {
  React.useEffect(() => {
    if (!MOBILE.installable || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register(`${base}/sw.js`, { scope: `${base}/` }).catch((err) => {
      console.warn("[pwa] the service worker could not be registered:", err);
    });
    const onPrompt = (e: Event) => { e.preventDefault(); deferred = e as InstallPrompt; listeners.forEach((l) => l()); };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);
  return null;
}

/** "Install app": the browser's own prompt where there is one; on iOS, how
 *  to add it from the share sheet. Nothing when already installed. */
export function InstallButton({ className }: { className?: string }) {
  const [ready, setReady] = React.useState(false);
  const [hint, setHint] = React.useState(false);
  const [installed, setInstalled] = React.useState(true);
  React.useEffect(() => {
    setInstalled(isInstalled());
    setReady(deferred !== null);
    const l = () => setReady(true);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  if (!MOBILE.installable || installed) return null;
  const ios = isIOS();
  if (!ready && !ios) return null;
  return (
    <div className={"relative " + (className ?? "")}>
      <button type="button" data-install-app
        onClick={async () => {
          if (deferred) { await deferred.prompt(); const c = await deferred.userChoice; if (c.outcome === "accepted") { deferred = null; setReady(false); } return; }
          setHint((h) => !h);
        }}
        className="inline-flex h-9 items-center gap-1.5 rounded-full border border-border bg-card px-3 text-xs font-medium text-foreground hover:bg-muted">
        Install app
      </button>
      {hint && (
        <div role="dialog" className="absolute right-0 z-50 mt-2 w-64 rounded-xl border border-border bg-popover p-3 text-xs text-popover-foreground shadow-xl">
          Tap <span className="font-medium">Share</span>, then <span className="font-medium">Add to Home Screen</span>.
        </div>
      )}
    </div>
  );
}

function toKey(b64url: string): Uint8Array {
  const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
  const raw = atob((b64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Subscribe this device to the application's push, with the person's
 *  consent asked by the browser. Says why when it cannot. */
export async function subscribeToPush(): Promise<{ ok: boolean; why?: string }> {
  if (!MOBILE.push) return { ok: false, why: "This application does not send push notifications." };
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return { ok: false, why: "This browser cannot receive push notifications." };
  if (isIOS() && !isInstalled()) return { ok: false, why: "On iPhone, add the app to your Home Screen first, then turn notifications on from there." };
  const conf = await fetch(apiPath("/api/push")).then((r) => r.json()).catch(() => null);
  if (!conf?.enabled || !conf.publicKey) return { ok: false, why: "Push is not set up on this installation yet." };
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return { ok: false, why: "Notifications were not allowed." };
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toKey(String(conf.publicKey)) as BufferSource });
  const res = await fetch(apiPath("/api/push"), { method: "POST", headers: { "Content-Type": "application/json" },
                                                body: JSON.stringify({ subscription: sub.toJSON() }) });
  return res.ok ? { ok: true } : { ok: false, why: "The device could not be registered." };
}

export async function pushState(): Promise<"on" | "off" | "unavailable"> {
  if (!MOBILE.push || typeof window === "undefined" || !("serviceWorker" in navigator) || !("PushManager" in window)) return "unavailable";
  try {
    const reg = await navigator.serviceWorker.getRegistration(`${base}/`);
    const sub = await reg?.pushManager.getSubscription();
    return sub ? "on" : "off";
  } catch {
    return "off";
  }
}
