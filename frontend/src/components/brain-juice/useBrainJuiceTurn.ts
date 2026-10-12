"use client";

/**
 * One message to Smith in Brain Juice, his answer streamed back.
 *
 * Events (routers/brain_juice.py): `step` what he is doing, `delta` his words
 * as they come, `file` a screenshot he took, `board` the idea board changed,
 * `message` his whole answer, `handoff` the app made and its build to start,
 * `research` a study the Researcher started (or Smith read), `done`, `error`.
 */
import { useCallback, useRef, useState } from "react";
import type { Board, ChatEntry, FileMeta, Study } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export type Handoff = { project_id: string; org_id: string; app_name: string; opening: string };

type Handlers = {
  onBoard: (board: Board) => void;
  onFile: (file: FileMeta) => void;
  onMessage: (entry: ChatEntry) => void;
  onHandoff: (h: Handoff) => void;
  onStudy: (study: Study) => void;
};

export function useBrainJuiceTurn(orgId: string, sessionId: string | null, on: Handlers) {
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState("");
  const [steps, setSteps] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const handlers = useRef(on);
  handlers.current = on;

  const send = useCallback(
    async (text: string, files: string[]) => {
      if (!sessionId || busy) return;
      setBusy(true);
      setLive("");
      setSteps([]);
      setError(null);
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
      try {
        const res = await fetch(`${API_BASE}/api/orgs/${orgId}/brain-juice/${sessionId}/message`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ text, files }),
        });
        if (!res.ok || !res.body) {
          const detail = await res.text().catch(() => "");
          throw new Error(detail || `Smith could not be reached (HTTP ${res.status})`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let event = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const raw of lines) {
            const line = raw.replace(/\r$/, "");
            if (line.startsWith("event:")) {
              event = line.slice(6).trim();
              continue;
            }
            if (!line.startsWith("data:") || !event) continue;
            let data: any;
            try {
              data = JSON.parse(line.slice(5).trim());
            } catch {
              continue;
            }
            if (event === "delta") setLive((t) => t + String(data.text ?? ""));
            else if (event === "step") setSteps((s) => [...s, String(data.text ?? "")]);
            else if (event === "board") handlers.current.onBoard(data.board as Board);
            else if (event === "file") handlers.current.onFile(data.file as FileMeta);
            else if (event === "message") {
              handlers.current.onMessage(data as ChatEntry);
              setLive("");
            } else if (event === "handoff") handlers.current.onHandoff(data as Handoff);
            else if (event === "research") handlers.current.onStudy(data.job as Study);
            else if (event === "error") setError(String(data.message ?? "Something went wrong"));
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [orgId, sessionId, busy],
  );

  return { send, busy, live, steps, error };
}
