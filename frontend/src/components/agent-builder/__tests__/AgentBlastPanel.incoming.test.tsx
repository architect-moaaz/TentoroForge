/**
 * Find problems when real chats arrive from Watch live ("Send to Blast" / "Send to fix").
 *
 * The platform has already saved the chats as tests before this page is shown, so they come in with "My tests" by themselves. What is
 * pinned here is what the builder SEES on arrival: a note saying what came in (and what the fixer made of it), the fixer's proposals
 * as the usual fix cards that "Apply and test" works on, and that all of it is taken in once, not again when the page re-draws.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPut = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (u: string) => apiGet(u), post: (u: string, b: unknown) => apiPost(u, b), put: (u: string, b: unknown) => apiPut(u, b), delete: vi.fn() }, ApiError: class extends Error {} }));

import { AgentBlastPanel } from "../AgentBlastPanel";
import type { Incoming } from "@/lib/agent-recording";
import type { BlastFix } from "@/lib/agent-blast";

const RECORDED = [
  { id: "rec_aaa111", name: "Real chat: How many open tickets are there?", message: "How many open tickets are there?", kind: "recorded", expect: {}, judge: "A real chat from the running app." },
  { id: "rec_bbb222", name: "Real chat: Close ticket 99999", message: "Close ticket 99999", kind: "recorded", expect: {}, judge: "In real life it went wrong." },
];
const FIX: BlastFix = { id: "fix_1", kind: "instruction_add", title: "Check ids first", why: "It acted on a made-up id in a real chat.", fixesTests: ["rec_bbb222"], nodeId: "sp", text: "Never act on an id you were not given." };
const GRAPH = { id: "app_assistant", name: "A", edges: [], nodes: [{ id: "sp", data: { nodeType: "system_prompt", config: { prompt: "You help." } } }] };

const incomingOf = (over: Partial<Incoming> = {}): Incoming => ({
  key: 1001, sent: 2, added: 2, alreadyThere: 0, leftOut: 0, fixes: [], problems: { rec_bbb222: ["The chat failed: boom."] }, fixRequested: false, ...over,
});

const onApplyFix = vi.fn();
const onTaken = vi.fn();
const fetchMock = vi.fn();
let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  [apiGet, apiPost, apiPut, onApplyFix, onTaken, fetchMock].forEach((f) => f.mockReset());
  (globalThis as any).fetch = fetchMock;
  apiGet.mockImplementation(async (u: string) => (u.endsWith("/blast/bombs") ? { bombs: [], maxTests: 20, maxRepeats: 3, perBomb: 2 } : { scenarios: RECORDED }));
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
const view = (incoming?: Incoming) => (
  <AgentBlastPanel projectId="p1" agentId="app_assistant" graph={GRAPH} onApplyFix={onApplyFix} incoming={incoming} onIncomingTaken={onTaken} />
);
async function show(incoming?: Incoming) {
  await act(async () => { root.render(view(incoming)); });
  await settle();
}
const note = () => container.querySelector('[data-testid="blast-arrival"]');
const cards = () => [...container.querySelectorAll('[data-testid="blast-fix"]')];

describe("chats arriving from Watch live", () => {
  it("says what came in, and how many had problems, with the recorded chats waiting in My tests", async () => {
    await show(incomingOf());
    expect(note()?.textContent).toContain("Added 2 real chats from Watch live to My tests (1 of them had problems).");
    expect(note()?.getAttribute("role")).toBe("note");
    // they are the saved tests, listed (My tests is opened for the builder)
    expect(container.querySelector('[data-testid="blast-mine"]')?.textContent).toContain("Real chat: Close ticket 99999");
    expect(cards(), "nothing was asked of the fixer").toHaveLength(0);
  });

  it("says so when every chat went well, and when they were all there already", async () => {
    await show(incomingOf({ problems: {} }));
    expect(note()?.textContent).toContain("(none had problems)");
    await show(incomingOf({ key: 1002, added: 0, alreadyThere: 2, problems: {} }));
    expect(note()?.textContent).toContain("Those 2 real chats were already in My tests (none had problems).");
  });

  it("puts the fixer's proposals among the usual fix cards, and says how many", async () => {
    await show(incomingOf({ fixes: [FIX], fixRequested: true }));
    expect(note()?.textContent).toContain("The fixer proposed 1 fix below.");
    expect(cards()).toHaveLength(1);
    expect(cards()[0].textContent).toContain("Check ids first");
    expect(cards()[0].textContent, "it says it helps the saved test").toContain("helps 1 test");
  });

  it("says the fixer found nothing, instead of leaving the builder wondering", async () => {
    await show(incomingOf({ fixes: [], fixRequested: true }));
    expect(note()?.textContent).toContain("The fixer found no safe fix.");
    expect(cards()).toHaveLength(0);
  });

  it("does not mention the fixer when it was not asked", async () => {
    await show(incomingOf({ fixes: [FIX], fixRequested: false }));
    expect(note()?.textContent).not.toContain("fixer");
  });

  it("Apply and test works on a recorded fix: it runs the saved test it was for, on the drawing with the fix", async () => {
    await show(incomingOf({ fixes: [FIX], fixRequested: true }));
    const enc = new TextEncoder();
    const events = [
      { type: "start", total: 1, repeats: 2 },
      { type: "result", result: { id: "rec_bbb222", name: "Real chat: Close ticket 99999", message: "Close ticket 99999", status: "passed", failures: [], response: "Which ticket?", toolCalls: [], blocked: false, runs: 2, passedRuns: 2, failedRuns: 0 } },
      { type: "done", summary: { passed: 1, failed: 0, flaky: 0, error: 0, total: 1 } },
    ];
    const chunks = events.map((e) => enc.encode(`data: ${JSON.stringify(e)}\n\n`));
    let i = 0;
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, text: async () => "", body: { getReader: () => ({ read: async () => (i < chunks.length ? { done: false, value: chunks[i++] } : { done: true, value: undefined }) }) } });
    const apply = [...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").trim().startsWith("Apply and test"))!;
    await act(async () => { apply.click(); });
    await settle(120);
    expect(onApplyFix).toHaveBeenCalledWith(FIX);
    const sent = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(sent.tests.map((t: any) => t.id)).toEqual(["rec_bbb222"]);
    expect(cards()[0].getAttribute("data-outcome")).toBe("worked");
  });

  it("can be dismissed, and lets the builder know it has taken the chats in", async () => {
    await show(incomingOf());
    expect(onTaken).toHaveBeenCalledTimes(1);
    await act(async () => { (container.querySelector('[data-testid="blast-arrival-dismiss"]') as HTMLElement).click(); });
    expect(note()).toBeNull();
  });
});

describe("taken in once", () => {
  it("does not add the same send again when the page draws again", async () => {
    const same = incomingOf({ fixes: [FIX], fixRequested: true });
    await show(same);
    await show({ ...same });
    await show(same);
    expect(cards(), "one card, not three").toHaveLength(1);
    expect(onTaken).toHaveBeenCalledTimes(1);
  });

  it("does not bring a dismissed note back when the same send is handed over again", async () => {
    const same = incomingOf();
    await show(same);
    await act(async () => { (container.querySelector('[data-testid="blast-arrival-dismiss"]') as HTMLElement).click(); });
    await show({ ...same });
    expect(note()).toBeNull();
  });

  it("takes in a second send as well, beside the first fixes", async () => {
    await show(incomingOf({ fixes: [FIX], fixRequested: true }));
    await show(incomingOf({ key: 2002, fixes: [{ ...FIX, id: "fix_2", title: "Ask before changing" }], fixRequested: true }));
    expect(cards().map((c) => c.textContent)).toEqual([expect.stringContaining("Check ids first"), expect.stringContaining("Ask before changing")]);
  });

  it("shows nothing at all when nothing arrived (the page is as it always was)", async () => {
    await show(undefined);
    expect(note()).toBeNull();
    expect(onTaken).not.toHaveBeenCalled();
  });
});
