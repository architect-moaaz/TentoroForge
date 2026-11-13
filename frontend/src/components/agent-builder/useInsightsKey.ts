"use client";

/**
 * The key a live app uses to send its chats to the platform, as the builder manages it.
 *
 * The platform keeps only a fingerprint of the key, so the FULL key exists in exactly one place for exactly one moment: the answer to
 * "create" (or "make a new one"). It is held here, in memory, only until the person says they have copied it (`dismiss`), or the view
 * goes away. It is never written to storage, never put in a log or an error sentence, and never read back from the platform.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export interface KeyStatus {
  exists: boolean;
  /** The first characters of the key, enough to tell two keys apart ("fik_ab12"). */
  prefix: string;
  createdAt: string | null;
  lastUsedAt: string | null;
  eventsLast24h: number;
}

/** The one-time reveal. */
export interface NewKey {
  key: string;
  ingestUrl: string;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const iso = (v: unknown): string | null => (typeof v === "string" && Number.isFinite(Date.parse(v)) ? v : null);

/** The platform's answer about the key, checked. Null when it is not one. */
export function asKeyStatus(raw: unknown): KeyStatus | null {
  if (!isObj(raw) || typeof raw.exists !== "boolean") return null;
  const n = typeof raw.eventsLast24h === "number" && Number.isFinite(raw.eventsLast24h) ? Math.max(0, Math.round(raw.eventsLast24h)) : 0;
  return {
    exists: raw.exists,
    prefix: typeof raw.prefix === "string" ? raw.prefix.slice(0, 16) : "",
    createdAt: iso(raw.createdAt),
    lastUsedAt: iso(raw.lastUsedAt),
    eventsLast24h: n,
  };
}

/** The answer to creating a key, checked: a key that looks like one and an address that is a web address. Null otherwise. */
export function asNewKey(raw: unknown): (NewKey & { prefix: string }) | null {
  if (!isObj(raw) || typeof raw.key !== "string" || typeof raw.ingestUrl !== "string") return null;
  if (!/^[A-Za-z0-9_]{8,128}$/.test(raw.key) || !/^https?:\/\/\S{1,300}$/.test(raw.ingestUrl)) return null;
  return { key: raw.key, ingestUrl: raw.ingestUrl, prefix: typeof raw.prefix === "string" ? raw.prefix.slice(0, 16) : raw.key.slice(0, 8) };
}

export function useInsightsKey(projectId: string) {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<NewKey | null>(null);
  const alive = useRef(true);
  const url = `/api/projects/${projectId}/agent-definitions/insights/key`;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const parsed = asKeyStatus(await api.get<unknown>(url));
      if (!alive.current) return;
      if (parsed) {
        setStatus(parsed);
        setError(null);
      } else setError("The platform answered about the key in a way this screen does not understand. Try again in a moment.");
    } catch {
      if (alive.current) setError("The key's details could not be loaded. Check your connection and try again.");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    alive.current = true;
    // A different project is a different key: nothing of the last one stays.
    setRevealed(null);
    setStatus(null);
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  /** Makes a key, or replaces the one there is (the old one stops working at once). */
  const create = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const made = asNewKey(await api.post<unknown>(url));
      if (!alive.current) return;
      if (!made) {
        setError("The platform did not send back a usable key. Try again; if it keeps happening, the platform may need an update.");
        return;
      }
      setRevealed({ key: made.key, ingestUrl: made.ingestUrl });
      setStatus({ exists: true, prefix: made.prefix, createdAt: new Date().toISOString(), lastUsedAt: null, eventsLast24h: 0 });
    } catch {
      if (alive.current) setError("The key could not be made. Nothing was changed. Try again in a moment.");
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [url]);

  /** Removes the key: the live app stops being able to send. */
  const remove = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await api.delete<unknown>(url);
      if (!alive.current) return;
      setRevealed(null);
      setStatus({ exists: false, prefix: "", createdAt: null, lastUsedAt: null, eventsLast24h: 0 });
    } catch {
      if (alive.current) setError("The key could not be removed. It still works. Try again in a moment.");
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [url]);

  /** The person has copied it: the platform will not show it again, and neither will this screen. */
  const dismiss = useCallback(() => setRevealed(null), []);

  return { status, loading, busy, error, revealed, load, create, remove, dismiss };
}
