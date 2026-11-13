/**
 * AgentBuilderPanel: recording chats in Watch live, and sending them to Find problems.
 *
 * What is pinned is the wiring the builder does: recording goes on while another page is shown, the chats of ANOTHER assistant are held
 * back, "Send to Blast" posts the chats (no drawing), "Send to fix" posts them with the drawing as it is now, and after a send the
 * builder lands in Find problems, where the note says what arrived. The platform and the live connection are faked; the chats are the
 * REAL captured one (lib/__fixtures__/watch-real-run.json).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, useSyncExternalStore } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import fixture from "@/lib/__fixtures__/watch-real-run.json";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (typeof window !== "undefined" && !(window as any).DOMMatrixReadOnly) {
  (window as any).DOMMatrixReadOnly = class { m22 = 1; constructor(_: unknown) {} };
}
if (typeof window !== "undefined" && !(window as any).matchMedia) {
  window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } })) as unknown as typeof window.matchMedia;
}
if (typeof window !== "undefined" && !(window as any).PointerEvent) {
  (window as any).PointerEvent = class extends Event {} as any;
}
if (typeof Element !== "undefined" && !(Element.prototype as any).hasPointerCapture) {
  (Element.prototype as any).hasPointerCapture = () => false;
  (Element.prototype as any).releasePointerCapture = () => {};
  (Element.prototype as any).setPointerCapture = () => {};
  (Element.prototype as any).scrollIntoView = () => {};
}

const apiGet = vi.fn(async (url: string): Promise<unknown> => (url.endsWith("/tests") ? { scenarios: [] } : []));
const apiPost = vi.fn(async (_url: string, _body?: unknown): Promise<unknown> => ({ saved: true }));
vi.mock("@/lib/api", () => ({
  api: { get: (u: string) => apiGet(u), post: (u: string, b?: unknown) => apiPost(u, b), put: vi.fn(async () => ({})), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

// The live connection is replaced by a small store the test feeds: what the builder does with the chats is what is under test.
const live = vi.hoisted(() => {
  let state: unknown = null;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(next: unknown) { state = next; listeners.forEach((l) => l()); },
    subscribe(l: () => void) { listeners.add(l); return () => listeners.delete(l); },
  };
});
vi.mock("../useAgentWatch", () => ({
  useAgentWatch: () => {
    const state = useSyncExternalStore(live.subscribe, live.get) as any;
    return { state, link: "connected", reason: null, suggestedUrl: null, connect: () => {}, disconnect: () => {}, select: () => {}, follow: () => {} };
  },
}));

import { AgentBuilderPanel } from "../AgentBuilderPanel";
import { useAgentBuilderStore } from "@/stores/agent-builder";
import { applyWatch, initialWatch, type WatchState } from "@/lib/agent-watch";
import type { LiveEvent } from "@/lib/agent-live";

const events = fixture.events as LiveEvent[];
const base = (): WatchState => applyWatch(initialWatch(), fixture.map as LiveEvent);
/** The real chat, as run `id` of assistant `agent`. */
const chat = (from: WatchState, id: string, agent: string): WatchState =>
  events.reduce((s, e) => applyWatch(s, { ...e, runId: id, ...(e.type === "run_start" ? { agentId: agent } : {}) }, Date.now() + 50), from);

const SEND = "/recordings/send";
const sends = () => apiPost.mock.calls.filter((c) => String(c[0]).endsWith(SEND));

let container: HTMLDivElement;
let root: Root;
const text = () => container.textContent ?? "";
const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`) as HTMLButtonElement;
const button = (label: RegExp) => [...container.querySelectorAll("button")].find((b) => label.test(b.textContent ?? ""))!;
const settle = (ms = 20) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
async function click(el: Element) {
  await act(async () => { (el as HTMLButtonElement).click(); });
  await settle();
}
const agentId = () => useAgentBuilderStore.getState().currentAgent!.id;

beforeEach(async () => {
  window.localStorage.clear();
  apiGet.mockClear();
  apiPost.mockReset();
  apiPost.mockResolvedValue({ saved: true });
  useAgentBuilderStore.getState().setCurrentAgent(null);
  (globalThis as any).fetch = vi.fn();
  live.set(base());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={qc}>
        <div style={{ width: 1000, height: 700 }}>
          <AgentBuilderPanel projectId="p1" />
        </div>
      </QueryClientProvider>,
    );
  });
  await settle(10);
  await click(button(/New Agent/));
  await settle();
  await click(button(/Watch live/));
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

/** Record three chats: two of this assistant, one of another. Leaves the strip showing them. */
async function recordThree() {
  await act(async () => { const n = byId("watch-record-count") as unknown as HTMLInputElement; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(n, "3"); n.dispatchEvent(new Event("input", { bubbles: true })); });
  await click(byId("watch-record-start"));
  await act(async () => { live.set(chat(chat(chat(base(), "r1", agentId()), "r2", "some_other_assistant"), "r3", agentId())); });
}

describe("recording from the builder", () => {
  it("shows the strip in Watch live, and keeps recording while Find problems is on screen", async () => {
    expect(byId("watch-record-idle")).toBeTruthy();
    await click(byId("watch-record-start"));
    await click(button(/Find problems/));
    expect(byId("watch-record"), "Watch live is not shown now").toBeNull();
    await act(async () => { live.set(chat(base(), "r1", agentId())); });
    // (the Watch live button stays "on" behind Find problems, so the first press turns it off and the second shows it again)
    await click(button(/Watch live/));
    await click(button(/Watch live/));
    expect(byId("watch-record-text").textContent, "the chat that finished meanwhile was kept").toBe("Recording: 1 of 5 chats");
  });

  it("Send to Blast sends only this assistant's chats, without a drawing, and lands in Find problems with a note", async () => {
    apiPost.mockImplementation(async (u: string) => (u.endsWith(SEND) ? { sent: 2, added: 1, alreadyThere: 1, leftOut: 0, tests: [], problems: { x: ["It was slow."] }, fixes: [] } : { saved: true }));
    await recordThree();
    expect(byId("watch-record-text").textContent).toBe("Recorded 3 chats, 3 with problems");
    await click(byId("watch-record-blast"));
    expect(sends()).toHaveLength(1);
    const [url, body] = sends()[0] as [string, any];
    expect(url).toBe(`/api/projects/p1/agent-definitions/${agentId()}${SEND}`);
    expect(body.fix).toBe(false);
    expect(body.graph, "no drawing needed for a plain send").toBeUndefined();
    expect(body.chats.map((c: any) => c.id), "the other assistant's chat is not sent").toEqual(["r1", "r3"]);
    // now in Find problems, and it says what arrived (and that one chat was held back)
    expect(byId("agent-blast")).toBeTruthy();
    expect(byId("blast-arrival").textContent).toContain("Added 1 real chat from Watch live to My tests (1 of them had problems). 1 chat left out (from another assistant, or not finished).");
    expect(byId("watch-record")).toBeNull();
  });

  it("Send to fix sends the drawing as it is, and the proposed fixes appear as fix cards", async () => {
    const fix = { id: "fix_1", kind: "instruction_add", title: "Answer quicker", why: "It took 34 seconds.", fixesTests: ["rec_1"], nodeId: "sp_entry", text: "Be brief." };
    apiPost.mockImplementation(async (u: string) => (u.endsWith(SEND) ? { sent: 2, added: 2, alreadyThere: 0, leftOut: 0, tests: [], problems: { rec_1: ["It was slow."] }, fixes: [fix] } : { saved: true }));
    await recordThree();
    await click(byId("watch-record-fix"));
    const body = sends()[0][1] as any;
    expect(body.fix).toBe(true);
    expect(body.graph).toMatchObject({ id: agentId(), name: "New Agent" });
    expect(body.graph.nodes.map((n: any) => n.id)).toEqual(["sp_entry"]);
    expect(byId("blast-arrival").textContent).toContain("The fixer proposed 1 fix below.");
    expect(container.querySelectorAll('[data-testid="blast-fix"]')).toHaveLength(1);
    expect(text()).toContain("Answer quicker");
  });

  it("does not show the arrival note again when the builder leaves Find problems and comes back", async () => {
    apiPost.mockImplementation(async (u: string) => (u.endsWith(SEND) ? { sent: 2, added: 2, alreadyThere: 0, leftOut: 0, tests: [], problems: {}, fixes: [] } : { saved: true }));
    await recordThree();
    await click(byId("watch-record-blast"));
    expect(byId("blast-arrival")).toBeTruthy();
    await click(button(/Find problems/)); // off
    await click(button(/Find problems/)); // on again
    expect(byId("agent-blast")).toBeTruthy();
    expect(byId("blast-arrival")).toBeNull();
  });

  it("a send the platform refuses stays in Watch live and says why", async () => {
    apiPost.mockImplementation(async (u: string) => {
      if (u.endsWith(SEND)) throw new Error("There are no finished chats of this assistant to send. Record some chats first.");
      return { saved: true };
    });
    await recordThree();
    await click(byId("watch-record-blast"));
    expect(byId("watch-record-result").getAttribute("role")).toBe("alert");
    expect(byId("watch-record-result").textContent).toContain("no finished chats of this assistant");
    expect(byId("agent-blast"), "still in Watch live").toBeNull();
    expect(byId("watch-record-text").textContent, "the chats are kept").toBe("Recorded 3 chats, 3 with problems");
  });

  it("when none of the chats are from this assistant, it says so without asking the platform", async () => {
    await click(byId("watch-record-start"));
    await act(async () => { live.set(chat(base(), "r1", "some_other_assistant")); });
    await click(byId("watch-record-stop"));
    await click(byId("watch-record-blast"));
    expect(sends()).toHaveLength(0);
    expect(byId("watch-record-result").textContent).toContain("None of these chats are from this assistant");
  });
});
