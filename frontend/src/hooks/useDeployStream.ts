import { useCallback, useRef, useState } from "react";

/**
 * SSE consumer for POST /api/projects/{id}/publish.
 *
 * EventSource only supports GET, and our publish endpoint is POST so
 * we can send auth + a JSON body. Use fetch + a ReadableStream reader,
 * parse SSE frames by hand (they're `data: <json>\n\n`).
 */
export interface DeployEvent {
  stage:
    | "snapshot"
    | "provision_db"
    | "migrate"
    | "upload"
    | "build"
    | "activate"
    | "smoke"
    | "smoke_failed"
    | "done"
    | "error";
  message: string;
  progress?: number | null;
  data?: Record<string, unknown> | null;
}

type Status = "idle" | "running" | "done" | "warning" | "error";

export function useDeployStream(projectId: string | undefined) {
  const [events, setEvents] = useState<DeployEvent[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(async () => {
    if (!projectId) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setEvents([]);
    setStatus("running");
    try {
      const token =
        typeof window !== "undefined"
          ? window.localStorage.getItem("token") ?? ""
          : "";
      const res = await fetch(`/api/projects/${projectId}/publish`, {
        method: "POST",
        credentials: "include",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: ac.signal,
      });
      if (!res.ok || !res.body) {
        setStatus("error");
        setEvents((prev) => [
          ...prev,
          { stage: "error", message: `HTTP ${res.status}` },
        ]);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // Parse SSE frames delimited by \n\n
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = frame.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          try {
            const evt = JSON.parse(line.slice(5).trim()) as DeployEvent;
            setEvents((prev) => [...prev, evt]);
            if (evt.stage === "done") setStatus("done");
            if (evt.stage === "error") setStatus("error");
            // smoke_failed is a terminal state: the app is live but its
            // database is broken. Surface with a distinct "warning" status
            // so the UI can show the URL alongside the smoke error.
            if (evt.stage === "smoke_failed") setStatus("warning");
          } catch (e) {
            // Malformed frame — skip
            console.warn("SSE parse", e);
          }
        }
      }
      // Stream ended without a terminal frame — best-effort mark done
      // if last event was a positive stage.
      setStatus((cur) => {
        if (cur !== "running") return cur;
        const last = events.at(-1)?.stage;
        if (last === "done") return "done";
        if (last === "smoke_failed") return "warning";
        return "error";
      });
    } catch (err: unknown) {
      if ((err as { name?: string })?.name === "AbortError") return;
      setStatus("error");
      setEvents((prev) => [
        ...prev,
        { stage: "error", message: String(err) },
      ]);
    }
  }, [projectId]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setStatus("idle");
  }, []);

  const reset = useCallback(() => {
    setEvents([]);
    setStatus("idle");
  }, []);

  return { events, status, start, cancel, reset };
}
