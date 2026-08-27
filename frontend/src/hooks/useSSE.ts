import { useCallback, useRef } from "react";
import { useChatStore } from "@/stores/chat";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
const MAX_RECONNECT_ATTEMPTS = 3;

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const lastIdxRef = useRef<number>(-1);
  const projectIdRef = useRef<string | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const onCompleteRef = useRef<(() => void) | undefined>(undefined);
  const terminalRef = useRef<boolean>(false);

  const { startStreaming, handleSSEEvent, stopStreaming, setError } =
    useChatStore();

  /** Parse SSE lines from a ReadableStream reader, dispatching events. */
  const processStream = useCallback(
    async (reader: ReadableStreamDefaultReader<Uint8Array>, isReconnect: boolean) => {
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          // Skip SSE comments (heartbeats)
          if (line.startsWith(":")) continue;

          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const dataStr = line.slice(5).trim();
            if (dataStr && currentEvent) {
              try {
                const data = JSON.parse(dataStr);

                // Handle session event — store session_id, don't dispatch
                if (currentEvent === "session") {
                  sessionIdRef.current = data.session_id;
                  currentEvent = "";
                  continue;
                }

                // Track _idx for reconnect
                if (typeof data._idx === "number") {
                  if (isReconnect && data._idx <= lastIdxRef.current) {
                    // Dedup — already seen this event
                    currentEvent = "";
                    continue;
                  }
                  lastIdxRef.current = data._idx;
                }

                // Strip _idx before dispatching
                const { _idx, ...cleanData } = data;
                handleSSEEvent({ event: currentEvent, data: cleanData });

                // Terminal events
                if (
                  currentEvent === "complete" ||
                  currentEvent === "refine_complete" ||
                  currentEvent === "error"
                ) {
                  terminalRef.current = true;
                  onCompleteRef.current?.();
                }
              } catch {
                // Skip malformed JSON
              }
            }
            currentEvent = "";
          }
        }
      }
    },
    [handleSSEEvent],
  );

  /** Attempt to reconnect to an in-progress generation via the replay endpoint. */
  const attemptReconnect = useCallback(
    async () => {
      const sessionId = sessionIdRef.current;
      const projectId = projectIdRef.current;
      if (!sessionId || !projectId) {
        setError("Connection lost — no session to reconnect");
        stopStreaming();
        return;
      }

      if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
        setError("Connection lost — reconnect failed after multiple attempts");
        stopStreaming();
        return;
      }

      const attempt = reconnectAttemptsRef.current;
      reconnectAttemptsRef.current += 1;
      const delay = Math.pow(2, attempt) * 1000; // 1s, 2s, 4s
      await new Promise((r) => setTimeout(r, delay));

      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("token")
            : null;

        const since = lastIdxRef.current + 1;
        const controller = new AbortController();
        abortRef.current = controller;

        const response = await fetch(
          `${API_BASE}/api/projects/${projectId}/generation/${sessionId}/events?since=${since}`,
          {
            method: "GET",
            headers: {
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          throw new Error(`Reconnect failed: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body on reconnect");

        reconnectAttemptsRef.current = 0; // reset on successful connection
        await processStream(reader, true);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        // Try again if we have attempts left
        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          await attemptReconnect();
        } else {
          setError("Connection lost — reconnect failed after multiple attempts");
          stopStreaming();
        }
      }
    },
    [processStream, setError, stopStreaming],
  );

  const startStream = useCallback(
    async (
      url: string,
      body: Record<string, unknown>,
      onComplete?: () => void,
    ) => {
      // Abort any existing stream
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      // Reset refs
      sessionIdRef.current = null;
      lastIdxRef.current = -1;
      reconnectAttemptsRef.current = 0;
      terminalRef.current = false;
      onCompleteRef.current = onComplete;

      // Extract projectId from URL (e.g. /api/projects/{id}/generate)
      const match = url.match(/\/api\/projects\/([^/]+)\//);
      projectIdRef.current = match ? match[1] : null;

      startStreaming();

      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("token")
            : null;

        const response = await fetch(`${API_BASE}${url}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({
            detail: response.statusText,
          }));
          throw new Error(err.detail || err.message || "Request failed");
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body");

        await processStream(reader, false);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;

        // If we have a session and haven't seen a terminal event, try reconnecting
        if (sessionIdRef.current && !terminalRef.current) {
          await attemptReconnect();
        } else {
          setError((err as Error).message);
          stopStreaming();
        }
      }
    },
    [startStreaming, processStream, attemptReconnect, setError, stopStreaming],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
    stopStreaming();
  }, [stopStreaming]);

  return { startStream, abort };
}
