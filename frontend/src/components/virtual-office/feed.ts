// THE FOUNDRY HEARS EVERY JOB. It used to hear only the build the Smith panel
// was streaming (through `officeBridge`): a turn, a fix, the checks, the
// process trials, a publish or a background build moved no one. It now reads
// the project's own feed — every job's run ledger, narrated on the server
// (`GET /api/projects/{id}/office`, `services/office_feed.py`) — while a
// Foundry is on screen. One stream per project however many Foundries show it
// (the tab and the chat card), so no event is told twice.
import { authFetch } from "@/lib/api";
import { useOfficeStore } from "./OfficeStateManager";
import type { OfficeEvent } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
const RETRY_MS = 3000;

type Live = { watchers: number; stop: () => void };
const live = new Map<string, Live>();

/** Split an SSE body into its `office` frames' data. Exported for the tests. */
export function officeFrames(buffer: string): { events: OfficeEvent[]; rest: string } {
  const events: OfficeEvent[] = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  for (const part of parts) {
    let name = "message";
    let data = "";
    for (const line of part.split("\n")) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (name !== "office" || !data) continue;
    try {
      events.push(JSON.parse(data) as OfficeEvent);
    } catch {
      // a frame that is not JSON is not an event
    }
  }
  return { events, rest };
}

function open(projectId: string): () => void {
  let stopped = false;
  let controller: AbortController | null = null;

  const run = async () => {
    while (!stopped) {
      controller = new AbortController();
      try {
        const res = await authFetch(`${API_BASE}/api/projects/${projectId}/office`, { signal: controller.signal });
        if (!res.ok || !res.body) throw new Error(`office feed ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { events, rest } = officeFrames(buffer);
          buffer = rest;
          const tell = useOfficeStore.getState().handleEvent;
          for (const e of events) {
            try {
              tell(e);
            } catch {
              // the Foundry is a picture of the work, never a reason to stop reading it
            }
          }
        }
      } catch {
        // dropped or refused: try again shortly, while someone is still watching
      }
      if (!stopped) await new Promise((r) => setTimeout(r, RETRY_MS));
    }
  };
  void run();
  return () => {
    stopped = true;
    controller?.abort();
  };
}

/** Watch a project's work in the Foundry; returns the call that stops watching. */
export function watchFoundry(projectId: string): () => void {
  const existing = live.get(projectId);
  if (existing) {
    existing.watchers += 1;
  } else {
    live.set(projectId, { watchers: 1, stop: open(projectId) });
  }
  let done = false;
  return () => {
    if (done) return;
    done = true;
    const entry = live.get(projectId);
    if (!entry) return;
    entry.watchers -= 1;
    if (entry.watchers <= 0) {
      entry.stop();
      live.delete(projectId);
    }
  };
}
