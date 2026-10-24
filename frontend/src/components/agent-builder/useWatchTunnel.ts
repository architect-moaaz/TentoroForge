"use client";

/**
 * The state of the tunnel to the builder's own computer, kept fresh while Watch live is open.
 *
 * It asks the platform every few seconds whether the computer is connected (the platform checks the tunnel's listener, which
 * exists exactly as long as the connection does), so the screen notices a connector starting, a laptop going to sleep, and a
 * network dropping, without anyone pressing anything. A check that fails keeps the last known state and says so; it never
 * wipes what the builder was looking at. A code is asked for on request and counted down here.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { NO_TUNNEL, asTunnelState, type Pairing, type TunnelState } from "@/lib/watch-tunnel";

const POLL_MS = 5000;

export function useWatchTunnel(projectId: string) {
  const [tunnel, setTunnel] = useState<TunnelState>(NO_TUNNEL);
  const [checked, setChecked] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [asking, setAsking] = useState(false);
  const live = useRef(true);
  const busy = useRef(false);
  const base = `/api/projects/${projectId}/agent-definitions/debug/tunnel`;

  const refresh = useCallback(async () => {
    if (busy.current) return; // a slow answer is never piled on
    busy.current = true;
    try {
      const raw = await api.get<unknown>(base);
      if (!live.current) return;
      setTunnel(asTunnelState(raw));
      setProblem(null);
    } catch (e) {
      if (live.current) setProblem(e instanceof Error ? e.message : "The platform could not be asked.");
    } finally {
      busy.current = false;
      if (live.current) setChecked(true);
    }
  }, [base]);

  useEffect(() => {
    live.current = true;
    void refresh();
    // Nothing to keep fresh when the platform has no tunnel (it runs on this computer): ask once, and again only if it appears.
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => {
      live.current = false;
      clearInterval(timer);
    };
  }, [refresh]);

  /** A new one-time code. The old one stays good until it expires, but only the newest is shown. */
  const pair = useCallback(async () => {
    setAsking(true);
    try {
      const p = await api.post<Pairing>(`${base}/pair`, {});
      if (!live.current) return;
      setPairing({ code: String(p.code), expiresAt: Number(p.expiresAt) });
      setProblem(null);
    } catch (e) {
      if (live.current) setProblem(e instanceof Error ? e.message : "A code could not be made.");
    } finally {
      if (live.current) setAsking(false);
    }
  }, [base]);

  /** Forget the connected computer: its key stops being accepted. */
  const forget = useCallback(async () => {
    try {
      await api.delete(base);
      if (live.current) {
        setPairing(null);
        await refresh();
      }
    } catch (e) {
      if (live.current) setProblem(e instanceof Error ? e.message : "The computer could not be disconnected.");
    }
  }, [base, refresh]);

  return { tunnel, checked, problem, pairing, asking, pair, forget, refresh, dismissPairing: () => setPairing(null) };
}
