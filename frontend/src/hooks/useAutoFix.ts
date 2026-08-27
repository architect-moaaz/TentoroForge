/**
 * useAutoFix — listens for runtime errors from the bridge and auto-fixes them.
 *
 * Flow:
 *   1. Bridge captures error → postMessage("design2ui:runtime-error", payload)
 *   2. This hook debounces duplicate errors (same file+line+message within 2s)
 *   3. Calls POST /api/projects/{id}/fix-error (SSE stream)
 *   4. Shows progress banner: "Error Identified → Auto Fix in progress → Fixed"
 *   5. After fix, waits for HMR reload (3s)
 *   6. If same error recurs, retries (max 3 attempts)
 *   7. After 3 failures, surfaces error to user
 */

import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
const PREFIX = "design2ui:";
const MAX_RETRIES = 3;
const HMR_WAIT_MS = 4000;  // wait for Next.js HMR after fix

export type AutoFixStatus =
  | "idle"
  | "detected"
  | "fixing"
  | "fixed"
  | "failed";

export interface AutoFixState {
  status: AutoFixStatus;
  message: string;
  errorFile: string;
  attempt: number;
  maxAttempts: number;
}

const IDLE_STATE: AutoFixState = {
  status: "idle",
  message: "",
  errorFile: "",
  attempt: 0,
  maxAttempts: MAX_RETRIES,
};

interface ErrorPayload {
  message: string;
  file: string;
  line: number;
  column: number;
  stack: string;
  type: string;
}

export function useAutoFix(projectId: string) {
  const [state, setState] = useState<AutoFixState>(IDLE_STATE);

  // Track retries per unique error
  const retriesRef = useRef<Map<string, number>>(new Map());
  // Debounce: ignore same error within window
  const lastErrorRef = useRef<{ key: string; time: number }>({ key: "", time: 0 });
  // Prevent concurrent fix attempts
  const fixingRef = useRef(false);
  // Abort controller for SSE
  const abortRef = useRef<AbortController | null>(null);
  // Timer for auto-dismiss success banner
  const dismissTimerRef = useRef<NodeJS.Timeout | null>(null);

  const errorKey = (e: ErrorPayload) => `${e.file}:${e.line}:${e.message.slice(0, 100)}`;

  const runFix = useCallback(
    async (error: ErrorPayload) => {
      const key = errorKey(error);
      const attempt = (retriesRef.current.get(key) || 0) + 1;
      retriesRef.current.set(key, attempt);

      if (attempt > MAX_RETRIES) {
        setState({
          status: "failed",
          message: `Could not auto-fix after ${MAX_RETRIES} attempts: ${error.message}`,
          errorFile: error.file,
          attempt,
          maxAttempts: MAX_RETRIES,
        });
        fixingRef.current = false;
        return;
      }

      setState({
        status: "fixing",
        message: `Auto-fixing ${error.file || "error"}... (attempt ${attempt}/${MAX_RETRIES})`,
        errorFile: error.file,
        attempt,
        maxAttempts: MAX_RETRIES,
      });

      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("token")
            : null;

        const controller = new AbortController();
        abortRef.current = controller;

        const response = await fetch(
          `${API_BASE}/api/projects/${projectId}/fix-error`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(error),
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          throw new Error(`Fix request failed: ${response.status}`);
        }

        // Process SSE stream for progress
        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";
        let currentEvent = "";
        let fixSuccess = false;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith(":")) continue;
            if (line.startsWith("event:")) {
              currentEvent = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              const dataStr = line.slice(5).trim();
              if (!dataStr || !currentEvent) continue;
              try {
                const data = JSON.parse(dataStr);

                if (currentEvent === "status") {
                  setState((prev) => ({
                    ...prev,
                    message: data.message || prev.message,
                  }));
                } else if (currentEvent === "fix_result") {
                  fixSuccess = data.success;
                  if (data.success) {
                    setState({
                      status: "fixed",
                      message: `Fixed: ${data.summary || error.message}`,
                      errorFile: error.file,
                      attempt,
                      maxAttempts: MAX_RETRIES,
                    });
                    // Auto-dismiss after 5 seconds
                    dismissTimerRef.current = setTimeout(() => {
                      setState(IDLE_STATE);
                    }, 5000);
                  }
                } else if (currentEvent === "fix_error") {
                  throw new Error(data.error || "Fix agent failed");
                }
              } catch (parseErr) {
                if (parseErr instanceof Error && parseErr.message !== "Fix agent failed") {
                  // JSON parse error — skip
                }
              }
              currentEvent = "";
            }
          }
        }

        if (!fixSuccess) {
          throw new Error("Fix did not produce a result");
        }

        // Wait for HMR to reload the page
        // If the same error fires again, the message listener will trigger another attempt
        fixingRef.current = false;
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          fixingRef.current = false;
          return;
        }
        setState({
          status: "failed",
          message: `Auto-fix failed: ${(err as Error).message}`,
          errorFile: error.file,
          attempt,
          maxAttempts: MAX_RETRIES,
        });
        fixingRef.current = false;
      }
    },
    [projectId],
  );

  // Listen for runtime errors from the bridge
  useEffect(() => {
    function handleMessage(e: MessageEvent) {
      if (!e.data || typeof e.data.type !== "string") return;
      if (!e.data.type.startsWith(PREFIX)) return;

      const type = e.data.type.slice(PREFIX.length);
      if (type !== "runtime-error") return;

      const error = e.data.payload as ErrorPayload;
      if (!error?.message) return;

      // Debounce: skip if same error within 2s
      const key = errorKey(error);
      const now = Date.now();
      if (
        key === lastErrorRef.current.key &&
        now - lastErrorRef.current.time < 2000
      ) {
        return;
      }
      lastErrorRef.current = { key, time: now };

      // Skip if already fixing
      if (fixingRef.current) return;

      // Check retry count
      const retries = retriesRef.current.get(key) || 0;
      if (retries >= MAX_RETRIES) return; // Already exhausted

      fixingRef.current = true;

      setState({
        status: "detected",
        message: `Error detected in ${error.file || "app"}: ${error.message.slice(0, 100)}`,
        errorFile: error.file,
        attempt: retries + 1,
        maxAttempts: MAX_RETRIES,
      });

      // Small delay to batch rapid errors, then fix
      setTimeout(() => runFix(error), 500);
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [runFix]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
    };
  }, []);

  const dismiss = useCallback(() => {
    setState(IDLE_STATE);
    if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
  }, []);

  return { autoFix: state, dismissAutoFix: dismiss };
}
