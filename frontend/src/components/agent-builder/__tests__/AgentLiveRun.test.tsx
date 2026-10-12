/**
 * The live run screen: connect to the running app, pick who to run as, send a message, and watch each step.
 *
 * The app and the platform are faked: `api.get` answers the status check, `fetch` answers the run with a stream of
 * events like the real app sends. What is pinned is what the builder SEES: a clear reason when the app cannot be
 * reached, the run's steps in order, the exact input and a warning on one that looks made up, the real data as a
 * table, "not run" for a change that was held back, and what the request asked the platform for.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (u: string) => apiGet(u), post: vi.fn(), put: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }));

import { AgentLiveRun } from "../AgentLiveRun";

const TOOLS = [
  { name: "get_ticket", kind: "data", description: "Look up one ticket", confirm: false, changes: false, inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"], additionalProperties: true } },
  { name: "update_ticket", kind: "data", description: "Change a ticket", confirm: true, changes: true, inputSchema: { type: "object", properties: { id: { type: "string" }, data: { type: "object" } }, required: ["id", "data"], additionalProperties: true } },
];
const STATUS_OK = {
  ok: true,
  agents: [{ id: "app_assistant", name: "Assistant", enabled: true }],
  users: [{ id: "u1", name: "Lena Ferraro", email: "lena@example.test", role: "Support" }, { id: "u2", name: "Pat", email: null, role: "Manager" }],
};

const EVENTS = [
  { type: "debug_start", t: 0, agent: { id: "app_assistant", name: "Assistant", model: null, systemPrompt: "You help with tickets.", maxTurns: 4, tools: TOOLS }, user: { id: "u1", name: "Lena Ferraro", email: null, role: "Support" }, allowChanges: false, draft: true },
  { type: "text", t: 10, content: "Let me check. " },
  { type: "model_call", t: 3000, n: 1, ms: 2990, inputTokens: 5000, outputTokens: 80, messages: 1, toolsRequested: ["get_ticket", "update_ticket"] },
  { type: "tool_call", t: 3001, id: "c1", tool: "get_ticket", input: { id: "1" } },
  { type: "tool_result", t: 3300, id: "c1", tool: "get_ticket", ok: true, result: { data: [{ id: "abc", subject: "Wrong colour", status: "open" }, { id: "def", subject: "Late", status: "open" }] }, chars: 120, cut: false },
  { type: "tool_call", t: 3301, id: "c2", tool: "update_ticket", input: { id: "abc", data: { status: "closed" } } },
  { type: "tool_faked", t: 3302, tool: "update_ticket", reason: "it changes data" },
  { type: "tool_result", t: 3303, id: "c2", tool: "update_ticket", ok: true, result: { ok: true, debug_note: "Not run" }, chars: 40, cut: false },
  { type: "text", t: 3500, content: "I would close it." },
  { type: "model_call", t: 5000, n: 2, ms: 1500, inputTokens: 5400, outputTokens: 20, messages: 3, toolsRequested: [] },
  { type: "done", t: 5001, conversationId: "conv-1", tokens: { input: 10400, output: 100 }, turns: 2 },
];

function sse(events: unknown[]) {
  const enc = new TextEncoder();
  const chunks = events.map((e) => enc.encode(`data: ${JSON.stringify(e)}\n\n`));
  let i = 0;
  return { ok: true, status: 200, body: { getReader: () => ({ read: async () => (i < chunks.length ? { done: false, value: chunks[i++] } : { done: true, value: undefined }) }) }, text: async () => "" };
}

const fetchMock = vi.fn();
let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  window.localStorage.clear(); // the screen remembers the app address; one test's must not leak into the next
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

const wait = (ms = 20) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
const text = () => container.textContent ?? "";
const el = (label: string) => container.querySelector(`[aria-label="${label}"]`) as HTMLElement;

async function mount() {
  await act(async () => {
    root.render(<AgentLiveRun projectId="p1" agentId="app_assistant" agentName="Assistant" nodes={[{ id: "n1" } as any]} />);
  });
}
const button = (label: string) => [...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").trim() === label)!;
async function click(e: Element) { await act(async () => { (e as HTMLElement).click(); }); }
async function type(e: Element, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => { setter.call(e, value); e.dispatchEvent(new Event("input", { bubbles: true })); });
}

describe("AgentLiveRun", () => {
  it("says why when the app cannot be used, and offers nothing to run until it can", async () => {
    apiGet.mockResolvedValue({ ok: false, reason: "Could not reach the app at http://localhost:3000. Is it running?" });
    await mount();
    expect((el("Message") as HTMLInputElement).disabled).toBe(true);
    await click(button("Connect"));
    await wait();
    expect(apiGet).toHaveBeenCalledWith("/api/projects/p1/agent-definitions/debug/status?app_url=http%3A%2F%2Flocalhost%3A3000");
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Is it running?");
    expect((el("Message") as HTMLInputElement).disabled).toBe(true);
    expect(el("Run as")).toBeNull();
  });

  it("offers this project's app when the address belongs to another, and uses it in one click", async () => {
    apiGet.mockImplementation(async (u: string) =>
      u.includes("3001") ? STATUS_OK : { ok: false, reason: "Nothing at http://localhost:3000 accepted this project's key, but this project's app is running at http://localhost:3001.", suggestedUrl: "http://localhost:3001" });
    await mount();
    await click(button("Connect"));
    await wait();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("running at http://localhost:3001");
    await click(button("Use http://localhost:3001"));
    await wait();
    expect(apiGet).toHaveBeenLastCalledWith("/api/projects/p1/agent-definitions/debug/status?app_url=http%3A%2F%2Flocalhost%3A3001");
    expect((el("App address") as HTMLInputElement).value).toBe("http://localhost:3001");
    expect(el("Run as")).not.toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it("connects, lists the people, and says changes are not run", async () => {
    apiGet.mockResolvedValue(STATUS_OK);
    await mount();
    await click(button("Connect"));
    await wait();
    const options = [...(el("Run as") as HTMLSelectElement).options].map((o) => o.textContent);
    expect(options).toEqual(["Lena Ferraro (Support)", "Pat (Manager)"]);
    expect(text()).toContain("Anything that changes data is shown but not run.");
    expect((el("Run changes for real") as HTMLInputElement).checked).toBe(false);
    await click(el("Run changes for real"));
    expect(text()).toContain("Changes WILL really be made.");
  });

  it("runs a message and shows every step: the given, the model, the exact inputs, the data, the answer", async () => {
    apiGet.mockResolvedValue(STATUS_OK);
    fetchMock.mockResolvedValue(sse(EVENTS));
    await mount();
    await click(button("Connect"));
    await wait();
    await type(el("Message"), "close the oldest ticket");
    await click(el("Send"));
    await wait(60);

    // what was asked of the platform
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/projects/p1/agent-definitions/app_assistant/debug-run");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({ app_url: "http://localhost:3000", message: "close the oldest ticket", as_user_id: "u1", allow_changes: false, use_draft: true });
    expect(body.graph).toMatchObject({ id: "app_assistant", name: "Assistant" });
    expect(body.session_id).toBeTruthy();

    expect(container.querySelector('[data-testid="live-given"]')?.textContent).toContain("running as Lena Ferraro (Support)");
    expect(container.querySelectorAll('[data-testid="live-model"]')).toHaveLength(2);
    expect(container.querySelector('[data-testid="live-model"]')?.textContent).toContain("3.0 s");
    expect(container.querySelector('[data-testid="live-model"]')?.textContent).toContain("5,000 tokens in");
    expect(container.querySelector('[data-testid="live-model"]')?.textContent).toContain("Let me check.");

    const tools = [...container.querySelectorAll('[data-testid="live-tool"]')];
    expect(tools).toHaveLength(2);
    expect(tools[0].textContent).toContain("get_ticket");
    expect(tools[0].textContent).toContain('"id": "1"');
    expect(tools[0].querySelector('[data-testid="live-problems"]')?.textContent).toContain("may have been made up");
    expect(tools[0].querySelector("table")?.textContent).toContain("Wrong colour");
    expect(tools[1].textContent).toContain("not run");
    expect(tools[1].textContent).toContain("it changes data");
    expect(tools[1].querySelector('[data-testid="live-problems"]')).toBeNull();

    expect(container.querySelector('[data-testid="live-answer"]')?.textContent).toContain("I would close it.");
    expect(container.querySelector('[data-testid="live-totals"]')?.textContent).toContain("2 model calls");
    expect(container.querySelector('[data-testid="live-totals"]')?.textContent).toContain("10,400 tokens in");
  });

  it("opens the instructions and the tools the AI was given", async () => {
    apiGet.mockResolvedValue(STATUS_OK);
    fetchMock.mockResolvedValue(sse(EVENTS));
    await mount();
    await click(button("Connect"));
    await wait();
    await type(el("Message"), "hi");
    await click(el("Send"));
    await wait(60);
    expect(text()).not.toContain("You help with tickets.");
    await click(container.querySelector('[data-testid="live-given"] button')!);
    expect(text()).toContain("You help with tickets.");
    expect(text()).toContain("Look up one ticket");
    expect(text()).toContain("changes data · asks first");
  });

  it("carries the conversation into the next message, and starts over on request", async () => {
    apiGet.mockResolvedValue(STATUS_OK);
    fetchMock.mockImplementation(async () => sse(EVENTS));
    await mount();
    await click(button("Connect"));
    await wait();
    await type(el("Message"), "first");
    await click(el("Send"));
    await wait(60);
    await type(el("Message"), "yes");
    await click(el("Send"));
    await wait(60);
    const second = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string);
    const first = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(second.conversation_id).toBe("conv-1");
    expect(second.session_id).toBe(first.session_id);

    await click(button("New conversation"));
    await type(el("Message"), "again");
    await click(el("Send"));
    await wait(60);
    const third = JSON.parse((fetchMock.mock.calls[2][1] as RequestInit).body as string);
    expect(third.conversation_id).toBeNull();
    expect(third.session_id).not.toBe(first.session_id);
  });

  it("sends 'as applied' without the drawing, and 'for real' only when switched on", async () => {
    apiGet.mockResolvedValue(STATUS_OK);
    fetchMock.mockResolvedValue(sse(EVENTS));
    await mount();
    await click(button("Connect"));
    await wait();
    const pick = el("Which agent") as HTMLSelectElement;
    await act(async () => { pick.value = "installed"; pick.dispatchEvent(new Event("change", { bubbles: true })); });
    await click(el("Run changes for real"));
    await type(el("Message"), "go");
    await click(el("Send"));
    await wait(60);
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({ use_draft: false, graph: null, allow_changes: true });
  });

  it("shows a failure from the platform in the run itself", async () => {
    apiGet.mockResolvedValue(STATUS_OK);
    fetchMock.mockResolvedValue(sse([{ type: "error", t: 1, message: "Could not reach the app at http://localhost:3000. Is it running?" }]));
    await mount();
    await click(button("Connect"));
    await wait();
    await type(el("Message"), "go");
    await click(el("Send"));
    await wait(60);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Is it running?");
  });

  it("is told when a run ends without finishing", async () => {
    apiGet.mockResolvedValue(STATUS_OK);
    fetchMock.mockResolvedValue(sse([EVENTS[0]]));
    await mount();
    await click(button("Connect"));
    await wait();
    await type(el("Message"), "go");
    await click(el("Send"));
    await wait(60);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("ended without finishing");
  });
});
