"use client";

/**
 * The connection to a running app, for watching its real chats live.
 *
 * Connecting is two steps: ask the platform whether the app can be watched at all (the same check the Live run
 * uses: is it running, does it accept this project's key, is it in development), then open the stream. The stream
 * is only "connected" once the app itself has said hello, so a green light means the app answered and accepted the
 * key, not just that a socket opened. A dropped stream is reconnected a few times with a short wait; an
 * unrecoverable one says why.
 */
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api } from "@/lib/api";
import { applyWatch, followLatest, initialWatch, selectRun, type WatchState } from "@/lib/agent-watch";
import { parseEvents, type LiveEvent } from "@/lib/agent-live";
import type { AgentEdgeSerialized, AgentNodeSerialized } from "@/types/agent-builder";

export type Link = "idle" | "checking" | "connecting" | "connected" | "reconnecting" | "failed";

type Action =
  | { kind: "event"; event: LiveEvent }
  | { kind: "reset" }
  | { kind: "select"; id: string }
  | { kind: "follow" };

function reduce(state: WatchState, a: Action): WatchState {
  switch (a.kind) {
    case "event":
      return applyWatch(state, a.event);
    case "select":
      return selectRun(state, a.id);
    case "follow":
      return followLatest(state);
    case "reset":
      return initialWatch();
  }
}

interface Options {
  projectId: string;
  agentId: string;
  agentName: string;
  nodes: AgentNodeSerialized[];
  edges: AgentEdgeSerialized[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
const WAITS = [1000, 2000, 4000, 8000, 8000, 8000];

interface Status {
  ok: boolean;
  reason?: string;
  suggestedUrl?: string;
}

export function useAgentWatch({ projectId, agentId, agentName, nodes, edges }: Options) {
  const [state, dispatch] = useReducer(reduce, undefined, initialWatch);
  const [link, setLink] = useState<Link>("idle");
  const [reason, setReason] = useState<string | null>(null);
  const [suggestedUrl, setSuggestedUrl] = useState<string | null>(null);
  const open = useRef(false);
  const abort = useRef<AbortController | null>(null);
  // The latest drawing, read when a connection is opened, without re-running anything when it changes.
  const drawing = useRef({ nodes, edges });
  drawing.current = { nodes, edges };

  const stop = useCallback(() => {
    open.current = false;
    abort.current?.abort();
    abort.current = null;
  }, []);

  useEffect(() => stop, [stop]);

  const stream = useCallback(
    async (appUrl: string) => {
      const token = typeof window !== "undefined" ? window.localStorage.getItem("token") : null;
      let everReady = false;
      for (let attempt = 0; open.current; attempt++) {
        const controller = new AbortController();
        abort.current = controller;
        setLink(everReady ? "reconnecting" : "connecting");
        let lost = "The connection dropped.";
        try {
          const res = await fetch(`${API_BASE}/api/projects/${projectId}/agent-definitions/debug/watch`, {
            method: "POST",
            signal: controller.signal,
            headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
            body: JSON.stringify({ app_url: appUrl, graph: { id: agentId, name: agentName, nodes: drawing.current.nodes, edges: [] } }),
          });
          if (!res.ok || !res.body) throw new Error((await res.text().catch(() => "")) || `The platform answered ${res.status}.`);
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          read: for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parsed = parseEvents(buffer);
            buffer = parsed.rest;
            for (const event of parsed.events) {
              if (event.type === "watch_ready") {
                everReady = true;
                attempt = 0;
                setLink("connected");
                setReason(null);
              }
              if (event.type === "error" && !event.runId) {
                lost = String(event.message ?? "The connection failed.");
                if (!everReady) {
                  // Refused before it ever worked: say why, and do not keep trying the same thing.
                  setReason(lost);
                  setLink("failed");
                  dispatch({ kind: "event", event });
                  open.current = false;
                  return;
                }
                break read; // it worked before: treat as a drop and try again
              }
              dispatch({ kind: "event", event });
            }
          }
        } catch (e) {
          if (!open.current) return; // the builder closed it
          lost = e instanceof Error ? e.message : lost;
          if (!everReady) {
            setReason(lost);
            setLink("failed");
            open.current = false;
            return;
          }
        }
        if (!open.current) return;
        if (attempt >= WAITS.length) {
          setReason(`Lost the connection to the app: ${lost}`);
          setLink("failed");
          dispatch({ kind: "event", event: { type: "error", message: lost } });
          open.current = false;
          return;
        }
        dispatch({ kind: "event", event: { type: "error", message: "The connection dropped. Trying again…" } });
        setLink("reconnecting");
        await new Promise((r) => setTimeout(r, WAITS[attempt]));
      }
    },
    [projectId, agentId, agentName],
  );

  const connect = useCallback(
    async (appUrl: string) => {
      stop();
      dispatch({ kind: "reset" });
      setReason(null);
      setSuggestedUrl(null);
      setLink("checking");
      try {
        const s = await api.get<Status>(`/api/projects/${projectId}/agent-definitions/debug/status?app_url=${encodeURIComponent(appUrl)}`);
        if (!s.ok) {
          setReason(s.reason ?? "The app could not be reached.");
          setSuggestedUrl(s.suggestedUrl ?? null);
          setLink("failed");
          return;
        }
      } catch (e) {
        setReason(e instanceof Error ? e.message : "The app could not be checked.");
        setLink("failed");
        return;
      }
      open.current = true;
      void stream(appUrl);
    },
    [projectId, stop, stream],
  );

  const disconnect = useCallback(() => {
    stop();
    dispatch({ kind: "reset" });
    setLink("idle");
    setReason(null);
    setSuggestedUrl(null);
  }, [stop]);

  return {
    state,
    link,
    reason,
    suggestedUrl,
    connect,
    disconnect,
    select: (id: string) => dispatch({ kind: "select", id }),
    follow: () => dispatch({ kind: "follow" }),
  };
}
