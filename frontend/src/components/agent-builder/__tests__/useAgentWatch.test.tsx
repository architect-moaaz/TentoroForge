/**
 * The connection to a running app, for watching live.
 *
 * Connecting asks the platform whether the app can be watched, then opens the stream; the light is green only when
 * the app itself has said hello. A refusal before it ever worked says why and stops; a drop after it worked is
 * retried; disconnecting closes the stream and forgets what was seen.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (u: string) => apiGet(u), post: vi.fn(), put: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }));

import { useAgentWatch } from "../useAgentWatch";

/** A stream the test feeds by hand, the way the app feeds it while someone chats. */
function controlled() {
  const enc = new TextEncoder();
  const queue: Uint8Array[] = [];
  let wake: (() => void) | null = null;
  let closed = false;
  const response = {
    ok: true,
    status: 200,
    text: async () => "",
    body: {
      getReader: () => ({
        read: async () => {
          for (;;) {
            if (queue.length) return { done: false, value: queue.shift()! };
            if (closed) return { done: true, value: undefined };
            await new Promise<void>((r) => (wake = r));
          }
        },
      }),
    },
  };
  return {
    response,
    push(e: unknown) { queue.push(enc.encode(`data: ${JSON.stringify(e)}\n\n`)); wake?.(); },
    end() { closed = true; wake?.(); },
  };
}

const fetchMock = vi.fn();
let container: HTMLDivElement;
let root: Root;
let api: ReturnType<typeof useAgentWatch>;

function Harness() {
  api = useAgentWatch({ projectId: "p1", agentId: "app_assistant", agentName: "Assistant", nodes: [{ id: "n1", type: "tool", position: { x: 0, y: 0 }, data: { label: "t", nodeType: "tool", config: {} } } as any], edges: [] });
  return (
    <div>
      <span data-testid="link">{api.link}</span>
      <span data-testid="reason">{api.reason ?? ""}</span>
      <span data-testid="runs">{api.state.order.length}</span>
    </div>
  );
}
const get = (id: string) => container.querySelector(`[data-testid="${id}"]`)!.textContent;
const wait = (ms = 20) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

beforeEach(() => {
  apiGet.mockReset();
  fetchMock.mockReset();
  (globalThis as any).fetch = fetchMock;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function mount() {
  await act(async () => { root.render(<Harness />); });
}

describe("useAgentWatch", () => {
  it("checks the app first, opens the stream, and is connected only when the app says hello", async () => {
    apiGet.mockResolvedValue({ ok: true });
    const s = controlled();
    fetchMock.mockResolvedValue(s.response);
    await mount();
    expect(get("link")).toBe("idle");
    await act(async () => { void api.connect("http://localhost:3001"); });
    await wait();
    expect(apiGet).toHaveBeenCalledWith("/api/projects/p1/agent-definitions/debug/status?app_url=http%3A%2F%2Flocalhost%3A3001");
    expect(get("link")).toBe("connecting");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/projects/p1/agent-definitions/debug/watch");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({ app_url: "http://localhost:3001", graph: { id: "app_assistant", name: "Assistant" } });
    expect(body.graph.nodes).toHaveLength(1);

    await act(async () => { s.push({ type: "platform_map", tools: { t: "n1" }, kinds: {} }); s.push({ type: "watch_ready", agents: [{ id: "app_assistant", name: "Assistant" }] }); });
    await wait();
    expect(get("link")).toBe("connected");
    expect(api.state.map?.tools).toEqual({ t: "n1" });
    expect(api.state.ready).toBe(true);
  });

  it("asks for everyone's chats, a role's, or one person's, and a person outranks a role", async () => {
    apiGet.mockResolvedValue({ ok: true });
    const sent: any[] = [];
    fetchMock.mockImplementation(async (_u: string, init: RequestInit) => { sent.push(JSON.parse(init.body as string)); return controlled().response; });
    await mount();
    for (const who of [{}, { role: "Admin" }, { userId: "u-1" }, { role: "Admin", userId: "u-1" }] as any[]) {
      await act(async () => { void api.connect("http://localhost:3000", who); });
      await wait();
    }
    expect(sent.map((b) => [b.role, b.user_id])).toEqual([[null, null], ["Admin", null], [null, "u-1"], [null, "u-1"]]);
  });

  it("collects a chat as it streams in", async () => {
    apiGet.mockResolvedValue({ ok: true });
    const s = controlled();
    fetchMock.mockResolvedValue(s.response);
    await mount();
    await act(async () => { void api.connect("http://localhost:3000"); });
    await wait();
    await act(async () => {
      s.push({ type: "watch_ready", agents: [] });
      s.push({ runId: "r1", t: 1, type: "run_start", agentId: "a", agentName: "A", user: { id: "u", name: "Lena", role: null, email: null }, message: "hello", conversationId: null });
      s.push({ runId: "r1", t: 5, type: "phase", phase: "input_check", ok: true });
    });
    await wait();
    expect(get("runs")).toBe("1");
    expect(api.state.runs.r1.live.phases[0]).toMatchObject({ phase: "input_check", ok: true });
    expect(api.state.selected).toBe("r1");
  });

  it("says why when the platform cannot reach the app, offering this project's app if it is elsewhere, and opens no stream", async () => {
    apiGet.mockResolvedValue({ ok: false, reason: "Nothing at http://localhost:3000 accepted this project's key.", suggestedUrl: "http://localhost:3001" });
    await mount();
    await act(async () => { await api.connect("http://localhost:3000"); });
    await wait();
    expect(get("link")).toBe("failed");
    expect(get("reason")).toContain("accepted this project's key");
    expect(api.suggestedUrl).toBe("http://localhost:3001");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says why when the platform itself cannot be asked", async () => {
    apiGet.mockRejectedValue(new Error("Network error"));
    await mount();
    await act(async () => { await api.connect("http://localhost:3000"); });
    await wait();
    expect(get("link")).toBe("failed");
    expect(get("reason")).toBe("Network error");
  });

  it("stops, with the reason, when the app refuses before it ever worked, and does not keep trying", async () => {
    apiGet.mockResolvedValue({ ok: true });
    const s = controlled();
    fetchMock.mockResolvedValue(s.response);
    await mount();
    await act(async () => { void api.connect("http://localhost:3000"); });
    await wait();
    await act(async () => { s.push({ type: "error", message: "The app did not accept the live run." }); });
    await wait(60);
    expect(get("link")).toBe("failed");
    expect(get("reason")).toContain("did not accept");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("stops when the platform answers with an error status", async () => {
    apiGet.mockResolvedValue({ ok: true });
    fetchMock.mockResolvedValue({ ok: false, status: 502, body: null, text: async () => "Bad gateway" });
    await mount();
    await act(async () => { void api.connect("http://localhost:3000"); });
    await wait(60);
    expect(get("link")).toBe("failed");
    expect(get("reason")).toBe("Bad gateway");
  });

  it("closes the stream and forgets everything on disconnect", async () => {
    apiGet.mockResolvedValue({ ok: true });
    const s = controlled();
    fetchMock.mockResolvedValue(s.response);
    await mount();
    await act(async () => { void api.connect("http://localhost:3000"); });
    await wait();
    await act(async () => {
      s.push({ type: "watch_ready", agents: [] });
      s.push({ runId: "r1", t: 1, type: "run_start", agentId: "a", agentName: "A", user: { id: "u", name: "x", role: null, email: null }, message: "m", conversationId: null });
    });
    await wait();
    expect(get("runs")).toBe("1");
    const signal = (fetchMock.mock.calls[0][1] as RequestInit).signal as AbortSignal;
    await act(async () => { api.disconnect(); });
    expect(signal.aborted).toBe(true);
    expect(get("link")).toBe("idle");
    expect(get("runs")).toBe("0");
    expect(api.state.ready).toBe(false);
  });

  it("reconnects after a drop that follows a good connection", async () => {
    apiGet.mockResolvedValue({ ok: true });
    const first = controlled();
    const second = controlled();
    fetchMock.mockResolvedValueOnce(first.response).mockResolvedValueOnce(second.response);
    await mount();
    await act(async () => { void api.connect("http://localhost:3000"); });
    await wait();
    await act(async () => { first.push({ type: "watch_ready", agents: [] }); });
    await wait();
    expect(get("link")).toBe("connected");
    await act(async () => { first.end(); });
    await wait();
    expect(get("link")).toBe("reconnecting");
    await wait(1300);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => { second.push({ type: "watch_ready", agents: [] }); });
    await wait();
    expect(get("link")).toBe("connected");
  }, 10000);
});
