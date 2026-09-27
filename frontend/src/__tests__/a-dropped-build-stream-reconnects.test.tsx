/**
 * A build that loses its connection is picked back up, not declared dead.
 *
 * The run streams over ONE long-lived request. Something between the browser
 * and the engine can end that request while the build is still going — a proxy
 * that caps how long a single connection may live, a suspended tab, a network
 * that blinked — and `reader.read()` then rejects. The panel used to call that
 * an error, freeze on it, and never look again: it also left its "I own the
 * stream" flag set, which is the flag that silences polling, so no reconnect
 * was even attempted and only a reload got the build back.
 *
 * The run itself is detached server-side and carries on regardless. So a drop
 * hands back to the run registry, which is what knows whether the build is
 * still going — and only if the registry has nothing to track does the drop
 * become an error the user is told about.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

import { useBlueprintRun, type BlueprintRun } from "@/hooks/useBlueprintRun";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const PROJECT = "11111111-1111-1111-1111-111111111111";

/** An SSE frame, as the engine writes it. */
const frame = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

/** A body that yields the given chunks and then dies the way a cut connection
 *  does — `read()` rejecting, not resolving `{done: true}`. */
function droppingBody(chunks: string[]) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    getReader: () => ({
      read: async () => {
        if (i < chunks.length) return { done: false, value: encoder.encode(chunks[i++]) };
        throw new TypeError("network error");
      },
    }),
  };
}

type Snapshot = Record<string, unknown>;

/** Whatever the registry is currently told to say about the run. */
let snapshot: Snapshot;
let streamBody: ReturnType<typeof droppingBody>;
let runPolls: number;

function installFetch() {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (String(url).endsWith("/smith/chat")) {
      return { ok: true, redirected: false, status: 200, body: streamBody, url } as unknown as Response;
    }
    if (String(url).endsWith(`/api/projects/${PROJECT}/run`)) {
      runPolls += 1;
      return {
        ok: true, redirected: false, status: 200, url,
        json: async () => snapshot,
      } as unknown as Response;
    }
    throw new Error(`unexpected fetch: ${init?.method ?? "GET"} ${url}`);
  });
}

let root: Root | null = null;
let latest: BlueprintRun;

function mount() {
  const el = document.createElement("div");
  document.body.appendChild(el);
  function Probe() {
    const { run, start } = useBlueprintRun(PROJECT);
    latest = run;
    (globalThis as { __start?: typeof start }).__start = start;
    return null;
  }
  act(() => {
    root = createRoot(el);
    root.render(<Probe />);
  });
}

const startRun = () =>
  (globalThis as { __start?: (o: { description: string }) => Promise<void> })
    .__start!({ description: "build it" });

beforeEach(() => {
  snapshot = { active: false, status: "idle" };
  runPolls = 0;
  streamBody = droppingBody([]);
  installFetch();
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("a dropped build stream reconnects", () => {
  it("keeps following a run the registry still reports as active", async () => {
    streamBody = droppingBody([
      frame("started", { projectId: PROJECT }),
      frame("plan", { nodes: ["requirements", "pages"], total: 2 }),
      frame("node:start", { node: "requirements", subjects: 1 }),
    ]);
    // The build is mid-flight when the connection is cut.
    snapshot = {
      active: true, phase: "build", stage: "Pages",
      nodesDone: 1, nodesTotal: 2, callsDone: 3,
      nodes: [
        { key: "requirements", state: "done", calls: 1 },
        { key: "pages", state: "running", calls: 2 },
      ],
      elapsedMs: 420_000,
    };

    mount();
    await act(async () => { await startRun(); });

    expect(latest.status).toBe("running");
    expect(latest.error).toBeNull();
    // The panel is following the registry, not frozen at the last frame it read.
    expect(runPolls).toBeGreaterThan(0);
    expect(latest.nodesDone).toBe(1);
    expect(latest.nodes.find((n) => n.key === "pages")?.state).toBe("running");
    expect(latest.reattachedStage).toBe("Pages");
  });

  it("reports the run's own outcome when it finished while nobody was reading", async () => {
    streamBody = droppingBody([frame("started", { projectId: PROJECT })]);
    snapshot = {
      active: false, status: "complete", nodesDone: 2, nodesTotal: 2,
      nodes: [{ key: "requirements", state: "done", calls: 1 },
              { key: "pages", state: "done", calls: 1 }],
    };

    mount();
    await act(async () => { await startRun(); });

    expect(latest.status).toBe("complete");
    expect(latest.error).toBeNull();
  });

  it("only calls the drop an error once the registry has nothing to track", async () => {
    vi.useFakeTimers();
    streamBody = droppingBody([frame("started", { projectId: PROJECT })]);
    snapshot = { active: false, status: "idle" };

    mount();
    await act(async () => { await startRun(); });

    // One idle answer is not proof — a restarted backend or a poll that raced
    // the registry looks exactly like this, so it asks again before deciding.
    expect(latest.status).toBe("running");
    const asked = runPolls;

    for (let i = 0; i < 6; i += 1) {
      await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    }
    expect(runPolls).toBeGreaterThan(asked);
    expect(latest.status).toBe("error");
    expect(latest.error).toMatch(/connection to the engine dropped/i);
  });
});
