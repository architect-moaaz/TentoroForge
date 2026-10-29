"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Figma, Loader2 } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export interface FigmaConnection {
  configured: boolean;
  connected: boolean;
  account?: { handle: string; email: string };
}

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Connect Figma, beside the place a Figma link is given.
 *
 * Forge read every design with one shared token, which opens only its owner's files: a client's
 * project shared with a tester read as "not found" (2026-10-29). Signing in here lets Forge read
 * the person's files as them (`/api/me/figma`). The sign-in runs in a window of its own so the
 * link and anything else typed here stay put; Figma's pages may cut that window off from this
 * one, so the status is asked for while it is open as well as listened for.
 *
 * Nothing here sees a token: the server keeps it and answers with the account's name.
 */
export function FigmaConnect({
  onStatus,
  className,
}: {
  /** Told whenever the connection is known or changes. */
  onStatus?: (status: FigmaConnection) => void;
  className?: string;
}) {
  const [status, setStatus] = useState<FigmaConnection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);
  const told = useRef(onStatus);
  told.current = onStatus;

  const refresh = useCallback(async (): Promise<FigmaConnection | null> => {
    try {
      const res = await fetch(`${API_BASE}/api/me/figma`, { credentials: "include", headers: authHeaders() });
      if (!res.ok) return null;
      const body = (await res.json()) as FigmaConnection;
      setStatus(body);
      told.current?.(body);
      return body;
    } catch {
      return null;
    }
  }, []);

  const stopPolling = () => {
    if (poll.current) clearInterval(poll.current);
    poll.current = null;
  };

  useEffect(() => {
    void refresh();
    const onMessage = (e: MessageEvent) => {
      const data = e.data as { source?: string; figma?: string; reason?: string } | null;
      if (!data || data.source !== "forge-figma") return;
      stopPolling();
      setBusy(false);
      if (data.figma === "connected") void refresh();
      else setError(data.reason || "Figma was not connected.");
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      stopPolling();
    };
  }, [refresh]);

  const connect = async () => {
    setError("");
    setBusy(true);
    // Opened now, inside the click, so the browser does not block it; pointed at Figma once the
    // address is known. Blocked anyway: the sign-in runs in this tab and comes back here.
    const popup = window.open("", "forge-figma-connect", "width=560,height=720");
    try {
      const res = await fetch(`${API_BASE}/api/me/figma/connect`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ return_to: window.location.href, popup: Boolean(popup) }),
      });
      const body = (await res.json().catch(() => null)) as { url?: string; detail?: unknown } | null;
      if (!res.ok || !body?.url) {
        popup?.close();
        setBusy(false);
        setError(typeof body?.detail === "string" ? body.detail : "Figma could not be connected. Try again.");
        return;
      }
      if (!popup) {
        window.location.href = body.url;
        return;
      }
      popup.location.href = body.url;
      const started = Date.now();
      stopPolling();
      poll.current = setInterval(async () => {
        const now = await refresh();
        const gone = popup.closed;
        if (now?.connected || gone || Date.now() - started > 5 * 60_000) {
          stopPolling();
          setBusy(false);
          if (!now?.connected && gone) setError("The Figma window was closed before the sign-in finished.");
        }
      }, 2000);
    } catch {
      popup?.close();
      setBusy(false);
      setError("Could not reach the server. Try again in a moment.");
    }
  };

  const disconnect = async () => {
    setError("");
    await fetch(`${API_BASE}/api/me/figma`, { method: "DELETE", credentials: "include", headers: authHeaders() })
      .catch(() => null);
    await refresh();
  };

  // No OAuth app on this platform: the token field beside this stays the way in.
  if (!status || !status.configured) return null;

  const who = status.account?.handle || status.account?.email || "your Figma account";
  return (
    <div className={className} data-testid="figma-connect">
      {status.connected ? (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
          <span>
            Figma connected as <span className="font-medium text-foreground">{who}</span>
            {status.account?.email && status.account.handle ? ` (${status.account.email})` : ""}
          </span>
          <button type="button" onClick={() => void connect()} disabled={busy} className="underline underline-offset-2 hover:text-foreground">
            Use another account
          </button>
          <button type="button" onClick={() => void disconnect()} disabled={busy} className="underline underline-offset-2 hover:text-foreground">
            Disconnect
          </button>
        </p>
      ) : (
        <button
          type="button"
          onClick={() => void connect()}
          disabled={busy}
          className="inline-flex h-8 items-center gap-1.5 rounded border border-current/25 bg-background px-3 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Figma className="h-3.5 w-3.5" />}
          {busy ? "Waiting for Figma…" : "Connect Figma"}
        </button>
      )}
      {error && (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
