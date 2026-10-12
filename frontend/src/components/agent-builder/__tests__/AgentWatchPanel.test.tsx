/**
 * The Watch-live panel: connect, then follow a real chat as it happens.
 *
 * The panel is presentational (the connection lives in useAgentWatch), so it is driven with states built from the
 * same events the app streams. What is pinned is what the builder SEES: the connection light and why it failed, the
 * message that came in, where the chat has got to, the checklist ticking off, the steps, and the reply.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (u: string) => apiGet(u), post: vi.fn(), put: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }));

import { AgentWatchPanel } from "../AgentWatchPanel";
import { applyWatch, initialWatch, type FlowMap, type WatchState } from "@/lib/agent-watch";
import type { LiveEvent } from "@/lib/agent-live";
import type { Link } from "../useAgentWatch";

const MAP: FlowMap = { tools: { list_tickets: "tl", update_ticket: "tu" }, kinds: { system_prompt: ["sp"], guardrail: ["g"] } };
const ev = (e: LiveEvent, runId = "r1"): LiveEvent => ({ runId, t: 1, ...e });
const state = (events: LiveEvent[], from: WatchState = { ...initialWatch(), map: MAP, ready: true, agents: [{ id: "app_assistant", name: "ResolveDesk Assistant" }] }) =>
  events.reduce((s, e) => applyWatch(s, e, 1000), from);

const START = ev({ type: "run_start", agentId: "a", agentName: "A", user: { id: "u1", name: "Lena", role: "Support", email: null }, message: "How many open tickets are there?", conversationId: null });
const CHECKS = [ev({ type: "phase", phase: "input_check", ok: true }), ev({ type: "phase", phase: "memory", messages: 0, summarised: false })];
const CALL1 = ev({ type: "model_start", n: 1, messages: 1, tools: 26, systemChars: 3150 });
const CHOSE = ev({ type: "model_call", n: 1, ms: 3400, inputTokens: 5400, outputTokens: 130, messages: 1, toolsRequested: ["list_tickets", "update_ticket"] });

let container: HTMLDivElement;
let root: Root;
const calls = { connect: vi.fn(), disconnect: vi.fn(), select: vi.fn(), follow: vi.fn() };

const OPTIONS = {
  roles: ["Admin", "Support Agent"],
  people: [{ id: "u-ada", name: "Ada Admin", role: "Admin" }, { id: "u-lena", name: "Lena Ferraro", role: "Support Agent" }],
  peopleNote: null,
};

beforeEach(() => {
  window.localStorage.clear();
  apiGet.mockReset();
  apiGet.mockResolvedValue(OPTIONS);
  Object.values(calls).forEach((f) => f.mockReset());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function mount(over: Partial<{ state: WatchState; link: Link; reason: string | null; suggestedUrl: string | null }> = {}) {
  await act(async () => {
    root.render(
      <AgentWatchPanel
        state={over.state ?? initialWatch()}
        link={over.link ?? "idle"}
        reason={over.reason ?? null}
        suggestedUrl={over.suggestedUrl ?? null}
        projectId="p1"
        onConnect={calls.connect}
        onDisconnect={calls.disconnect}
        onSelect={calls.select}
        onFollow={calls.follow}
      />,
    );
  });
}
const text = () => container.textContent ?? "";
const button = (label: string) => [...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").trim().startsWith(label))!;
const click = (e: Element) => act(async () => { (e as HTMLElement).click(); });

describe("connecting", () => {
  it("starts with instructions, and connects to the address typed, remembering it", async () => {
    await mount();
    expect(text()).toContain("Start your app, choose whose chats to watch, press Connect");
    expect(container.querySelector('[data-testid="watch-link"]')?.textContent).toContain("Not connected");
    const input = container.querySelector('[aria-label="App address"]') as HTMLInputElement;
    expect(input.value).toBe("http://localhost:3000");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => { setter.call(input, "http://localhost:3001"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await click(button("Connect"));
    expect(calls.connect).toHaveBeenCalledWith("http://localhost:3001", {});
    expect(window.localStorage.getItem("forge.liveRun.app.p1")).toBe("http://localhost:3001");
  });

  it("uses the address remembered for this project", async () => {
    window.localStorage.setItem("forge.liveRun.app.p1", "http://localhost:3001");
    await mount();
    expect((container.querySelector('[aria-label="App address"]') as HTMLInputElement).value).toBe("http://localhost:3001");
  });

  it("shows each stage of the connection, and offers to disconnect once it is working or open", async () => {
    await mount({ link: "checking" });
    expect(container.querySelector('[data-testid="watch-link"]')?.textContent).toContain("Checking the app");
    expect(button("Disconnect")).toBeTruthy();
    await mount({ link: "connecting" });
    expect(container.querySelector('[data-testid="watch-link"]')?.textContent).toContain("Connecting");
    await mount({ link: "reconnecting" });
    expect(container.querySelector('[data-testid="watch-link"]')?.textContent).toContain("reconnecting");
  });

  it("says it is verified and what it is connected to, and waits for a chat", async () => {
    await mount({ link: "connected", state: state([]) });
    expect(container.querySelector('[data-testid="watch-link"]')?.textContent).toContain("Connected");
    expect(container.querySelector('[data-testid="watch-connected-to"]')?.textContent).toContain("ResolveDesk Assistant");
    expect(container.querySelector('[data-testid="watch-connected-to"]')?.textContent).toContain("Verified with this project's key");
    expect(container.querySelector('[data-testid="watch-waiting"]')?.textContent).toContain("Waiting for a chat");
    await click(button("Disconnect"));
    expect(calls.disconnect).toHaveBeenCalled();
  });

  it("says why it could not connect, and offers this project's app when it is elsewhere", async () => {
    await mount({ link: "failed", reason: "Nothing at http://localhost:3000 accepted this project's key, but this project's app is running at http://localhost:3001.", suggestedUrl: "http://localhost:3001" });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("running at http://localhost:3001");
    await click(button("Use http://localhost:3001"));
    expect(calls.connect).toHaveBeenCalledWith("http://localhost:3001", {});
  });

  it("is honest that it shows real chats, connects as an observer and only watches", async () => {
    await mount();
    expect(text()).toContain("real chats from this development app");
    expect(text()).toContain("connects as an observer, not as any role or person");
    expect(text()).toContain("cannot change or stop a chat");
  });
});

describe("whose chats to watch", () => {
  const select = () => container.querySelector('[aria-label="Who to watch"]') as HTMLSelectElement;
  const choose = async (value: string) => { await act(async () => { select().value = value; select().dispatchEvent(new Event("change", { bubbles: true })); }); };
  const labels = () => [...select().querySelectorAll("option")].map((o) => o.textContent);
  const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 10)); });

  it("offers everyone, each role the app has, and each person, from the app itself", async () => {
    await mount();
    await settle();
    expect(apiGet).toHaveBeenCalledWith("/api/projects/p1/agent-definitions/handoff-options");
    expect(labels()).toEqual(["Everyone", "Admin", "Support Agent", "Ada Admin (Admin)", "Lena Ferraro (Support Agent)"]);
    expect(select().value).toBe("all");
    expect([...select().querySelectorAll("optgroup")].map((g) => g.label)).toEqual(["Anyone with the role", "One person"]);
  });

  it("connects watching the role or person chosen", async () => {
    await mount();
    await settle();
    await choose("role:Admin");
    await click(button("Connect"));
    expect(calls.connect).toHaveBeenLastCalledWith("http://localhost:3000", { role: "Admin" });
    await choose("user:u-lena");
    await click(button("Connect"));
    expect(calls.connect).toHaveBeenLastCalledWith("http://localhost:3000", { userId: "u-lena" });
    await choose("all");
    await click(button("Connect"));
    expect(calls.connect).toHaveBeenLastCalledWith("http://localhost:3000", {});
  });

  it("reconnects at once to a new choice while connected, and not before then", async () => {
    await mount({ link: "idle" });
    await settle();
    await choose("role:Admin");
    expect(calls.connect).not.toHaveBeenCalled();
    await mount({ link: "connected", state: state([]) });
    await settle();
    await choose("role:Support Agent");
    expect(calls.connect).toHaveBeenLastCalledWith("http://localhost:3000", { role: "Support Agent" });
  });

  it("remembers the choice for this project", async () => {
    await mount();
    await settle();
    await choose("user:u-ada");
    await click(button("Connect"));
    expect(window.localStorage.getItem("forge.watch.who.p1")).toBe("user:u-ada");
    act(() => root.unmount());
    root = createRoot(container);
    await mount();
    await settle();
    expect(select().value).toBe("user:u-ada");
  });

  it("says whose chats the app confirmed it is sending, and who it is waiting for", async () => {
    await mount({ link: "connected", state: { ...state([]), who: { role: "Admin" } } });
    expect(container.querySelector('[data-testid="watch-connected-to"]')?.textContent).toContain("Watching Admin chats only.");
    expect(container.querySelector('[data-testid="watch-waiting"]')?.textContent).toContain("anyone with the role Admin");
    await mount({ link: "connected", state: { ...state([]), who: { userId: "u-lena" } } });
    await settle();
    expect(container.querySelector('[data-testid="watch-connected-to"]')?.textContent).toContain("Lena Ferraro's chats only.");
    await mount({ link: "connected", state: state([]) });
    expect(container.querySelector('[data-testid="watch-connected-to"]')?.textContent).toContain("Watching everyone's chats.");
  });

  it("still lets everyone be watched when the app's roles cannot be listed, and says so", async () => {
    apiGet.mockRejectedValue(new Error("offline"));
    await mount();
    await settle();
    expect(labels()).toEqual(["Everyone"]);
    expect(text()).toContain("could not be listed, so everyone's chats are watched");
  });
});

describe("following a chat", () => {
  it("shows the message that came in, who sent it, and the first stage", async () => {
    await mount({ link: "connected", state: state([START]) });
    const card = container.querySelector('[data-testid="watch-message-in"]')!;
    expect(card.textContent).toContain("Message in from Lena (Support)");
    expect(card.textContent).toContain("How many open tickets are there?");
    expect(container.querySelector('[data-testid="watch-stage"]')?.textContent).toContain("Message received");
  });

  it("shows the AI being called, with what it was given", async () => {
    await mount({ link: "connected", state: state([START, ...CHECKS, CALL1, ev({ type: "text", content: "Let me look. " })]) });
    expect(container.querySelector('[data-testid="watch-stage"]')?.textContent).toContain("Calling the AI (call 1)");
    const running = container.querySelector('[data-testid="live-model-running"]')!;
    expect(running.textContent).toContain("Calling the AI…");
    expect(running.textContent).toContain("26 tools offered");
    expect(running.textContent).toContain("instructions 3,150 characters");
    expect(running.textContent).toContain("Let me look.");
    expect(container.querySelector('[data-testid="watch-checklist"]')).toBeNull();
  });

  it("makes the checklist the moment the AI chooses, and ticks it off one tool at a time", async () => {
    const chosen = state([START, ...CHECKS, CALL1, CHOSE]);
    await mount({ link: "connected", state: chosen });
    let items = [...container.querySelectorAll('[data-testid="watch-check-item"]')];
    expect(items.map((i) => [i.textContent!.includes("list_tickets"), i.getAttribute("data-status")])).toEqual([[true, "waiting"], [false, "waiting"]]);
    expect(container.querySelector('[data-testid="watch-stage"]')?.textContent).toContain("The AI chose: list_tickets, update_ticket");

    const mid = state([
      ev({ type: "tool_call", id: "c1", tool: "list_tickets", input: { filters: { status: "open" } }, t: 3500 }),
      ev({ type: "app_call", kind: "request", label: "/api/data/tickets", method: "GET", status: 200, ms: 300, ok: true }),
      ev({ type: "tool_result", id: "c1", tool: "list_tickets", ok: true, result: { data: [{ id: "abc", subject: "Wrong colour" }] }, chars: 60, t: 3800 }),
      ev({ type: "tool_call", id: "c2", tool: "update_ticket", input: { id: "abc", data: {} }, t: 3801 }),
    ], chosen);
    await mount({ link: "connected", state: mid });
    items = [...container.querySelectorAll('[data-testid="watch-check-item"]')];
    expect(items.map((i) => i.getAttribute("data-status"))).toEqual(["ok", "running"]);
    expect(items[0].textContent).toContain("done");
    expect(items[0].textContent).toContain("300 ms");
    expect(container.querySelector('[data-testid="watch-stage"]')?.textContent).toContain("Running update_ticket");
    const tools = [...container.querySelectorAll('[data-testid="live-tool"]')];
    expect(tools).toHaveLength(2);
    expect(tools[0].querySelector('[data-testid="live-calls"]')?.textContent).toContain("GET /api/data/tickets");
    expect(tools[0].querySelector("table")?.textContent).toContain("Wrong colour");
  });

  it("shows a held change as waiting for a yes, and a failed tool as failed", async () => {
    const s = state([START, ...CHECKS, CALL1, CHOSE,
      ev({ type: "tool_call", id: "c1", tool: "list_tickets", input: {} }),
      ev({ type: "tool_result", id: "c1", tool: "list_tickets", ok: false, error: "Not allowed" }),
      ev({ type: "tool_call", id: "c2", tool: "update_ticket", input: { id: "a", data: {} } }),
      ev({ type: "tool_result", id: "c2", tool: "update_ticket", ok: true, result: { held: true, needs_confirmation: true } })]);
    await mount({ link: "connected", state: s });
    const items = [...container.querySelectorAll('[data-testid="watch-check-item"]')];
    expect(items.map((i) => i.getAttribute("data-status"))).toEqual(["failed", "held"]);
    expect(items[1].textContent).toContain("waiting for a yes");
  });

  it("ends with the reply that was handed back, and the totals", async () => {
    const s = state([START, ...CHECKS, CALL1, ev({ type: "text", content: "There are 4 open tickets." }),
      ev({ type: "model_call", n: 1, ms: 2000, inputTokens: 5000, outputTokens: 20, messages: 1, toolsRequested: [] }),
      ev({ type: "phase", phase: "output_check", ok: true }),
      ev({ type: "done", conversationId: "c1", t: 2100 })]);
    await mount({ link: "connected", state: s });
    expect(container.querySelector('[data-testid="watch-stage"]')?.textContent).toContain("Answer sent");
    expect(container.querySelector('[data-testid="watch-reply"]')?.textContent).toContain("There are 4 open tickets.");
    expect(container.querySelector('[data-testid="watch-totals"]')?.textContent).toContain("1 AI call");
    expect(container.querySelector('[data-testid="watch-totals"]')?.textContent).toContain("5,000 tokens in");
    expect((container.textContent!.match(/There are 4 open tickets\./g) ?? []).length).toBe(1);
  });

  it("shows a refused message and a failed chat plainly", async () => {
    await mount({ link: "connected", state: state([START, ev({ type: "phase", phase: "input_check", ok: false, reason: "Too long" }), ev({ type: "blocked", stage: "input", reason: "That message is too long." })]) });
    expect(container.textContent).toContain("Refused: That message is too long.");
    await mount({ link: "connected", state: state([START, ev({ type: "error", message: "The model call failed" })]) });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("The model call failed");
  });

  it("says when a chat is with a person and the assistant stays quiet", async () => {
    await mount({ link: "connected", state: state([START, ...CHECKS, ev({ type: "phase", phase: "with_person", ref: "HO-1" }), ev({ type: "done", conversationId: "c" })]) });
    expect(container.querySelector('[data-testid="watch-stage"]')?.textContent).toContain("With a person on the team");
  });
});

describe("several chats", () => {
  const two = () => state([START, ev({ type: "done" }), { runId: "r2", t: 1, type: "run_start", agentId: "a", agentName: "A", user: { id: "u2", name: "Pat", role: null, email: null }, message: "Where is my order?", conversationId: null }]);

  it("lists them, newest selected, and switches when one is picked", async () => {
    await mount({ link: "connected", state: two() });
    const chips = [...container.querySelectorAll('[data-testid="watch-runs"] button')];
    expect(chips.map((c) => c.getAttribute("aria-pressed"))).toEqual(["true", "false"]);
    expect(chips[0].textContent).toContain("Pat");
    expect(container.querySelector('[data-testid="watch-message-in"]')?.textContent).toContain("Where is my order?");
    await click(chips[1]);
    expect(calls.select).toHaveBeenCalledWith("r1");
  });

  it("offers to follow the newest once an older one is picked", async () => {
    const s = { ...two(), follow: false, selected: "r1" };
    await mount({ link: "connected", state: s });
    expect(container.querySelector('[data-testid="watch-message-in"]')?.textContent).toContain("How many open tickets");
    await click(button("Follow the newest"));
    expect(calls.follow).toHaveBeenCalled();
  });
});
