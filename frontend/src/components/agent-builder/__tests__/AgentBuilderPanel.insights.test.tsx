/**
 * AgentBuilderPanel: the Insights page (cost and quality of the connected development app).
 *
 * What is pinned is the wiring the builder does and not the dashboard itself (that has its own tests): an Insights button next to Watch
 * live opens the page, which closes every other page and is closed by them; the Diagram button gets back to the drawing; the page reads
 * from the app that Watch live connected (and remembers it for the project across a reload), and is told nothing when Watch live was
 * never connected; and "Open Watch live" on the page goes to Watch live. The two panels are stand-ins that show what they were given.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (typeof window !== "undefined" && !(window as any).DOMMatrixReadOnly) {
  (window as any).DOMMatrixReadOnly = class { m22 = 1; constructor(_: unknown) {} };
}
if (typeof window !== "undefined" && !(window as any).matchMedia) {
  window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } })) as any;
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
vi.mock("@/lib/api", () => ({
  api: { get: (u: string) => apiGet(u), post: vi.fn(async () => ({})), put: vi.fn(async () => ({})), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const connect = vi.hoisted(() => vi.fn());
vi.mock("../useAgentWatch", () => ({
  useAgentWatch: () => ({
    state: { ready: false, agents: [], who: {}, runs: {}, order: [], selected: null, follow: true },
    link: "idle", reason: null, suggestedUrl: null, connect, disconnect: () => {}, select: () => {}, follow: () => {},
  }),
}));
// Insights shows "Coming soon" while INSIGHTS_READY is off; these tests are about the real page's wiring, so they switch it on.
vi.mock("../insights-ready", () => ({ INSIGHTS_READY: true }));
vi.mock("../AgentInsightsPanel", () => ({
  AgentInsightsPanel: (p: { appUrl: string; agentName: string; agentId: string; onOpenWatch?: () => void }) => (
    <div data-testid="insights-stub" data-app={p.appUrl} data-agent={p.agentName}>
      <button type="button" onClick={p.onOpenWatch}>stub-open-watch</button>
    </div>
  ),
}));
vi.mock("../AgentWatchPanel", () => ({
  AgentWatchPanel: (p: { onConnect: (where: string, who: object) => void }) => (
    <div data-testid="watch-stub">
      <button type="button" onClick={() => p.onConnect("tunnel", {})}>stub-connect</button>
    </div>
  ),
}));

import { AgentBuilderPanel } from "../AgentBuilderPanel";
import { useAgentBuilderStore } from "@/stores/agent-builder";

let container: HTMLDivElement;
let root: Root;
const q = (id: string) => container.querySelector(`[data-testid="${id}"]`);
const button = (label: RegExp) => [...container.querySelectorAll("button")].find((b) => label.test((b.textContent ?? "").trim()))!;
const settle = (ms = 20) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
async function click(el: Element) {
  await act(async () => { (el as HTMLButtonElement).click(); });
  await settle();
}
async function mount() {
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
}

beforeEach(() => {
  window.localStorage.clear();
  connect.mockClear();
  apiGet.mockClear();
  useAgentBuilderStore.getState().setCurrentAgent(null);
  (globalThis as any).fetch = vi.fn();
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("the Insights page in the builder", () => {
  it("has an Insights button that opens the page for this assistant, and the Diagram button leaves it", async () => {
    await mount();
    const insights = button(/^Insights$/);
    expect(insights, "next to Watch live in the toolbar").toBeDefined();
    expect(q("insights-stub")).toBeNull();
    await click(insights);
    expect(q("insights-stub")!.getAttribute("data-agent")).toBeTruthy();
    expect(insights.getAttribute("aria-pressed")).toBe("true");
    expect(button(/^Diagram$/).getAttribute("aria-pressed"), "not on the drawing now").toBe("false");
    await click(button(/^Diagram$/));
    expect(q("insights-stub")).toBeNull();
    expect(button(/^Insights$/).getAttribute("aria-pressed")).toBe("false");
  });

  it("closes the other pages when it opens, and is closed by each of them", async () => {
    await mount();
    await click(button(/Find problems/));
    expect(button(/Find problems/).getAttribute("aria-pressed")).toBe("true");
    await click(button(/^Insights$/));
    expect(q("insights-stub")).not.toBeNull();
    expect(button(/Find problems/).getAttribute("aria-pressed"), "Find problems made way").toBe("false");
    for (const other of [/Find problems/, /^Test$/, /Watch live/]) {
      await click(button(other));
      expect(q("insights-stub"), `${other} closes Insights`).toBeNull();
      await click(button(/^Insights$/));
      expect(q("insights-stub"), `Insights closes ${other} and opens again`).not.toBeNull();
    }
  });

  it("reads from the app Watch live connected, and remembers it for the project", async () => {
    await mount();
    await click(button(/^Insights$/));
    expect(q("insights-stub")!.getAttribute("data-app"), "Watch live never connected: nothing to read from").toBe("");
    await click(button(/Watch live/));
    await click(button(/stub-connect/));
    expect(connect).toHaveBeenCalledWith("tunnel", {});
    expect(window.localStorage.getItem("forge.watch.insightsApp.p1")).toBe("tunnel");
    await click(button(/^Insights$/));
    expect(q("insights-stub")!.getAttribute("data-app")).toBe("tunnel");
  });

  it("knows the app again after a reload, per project", async () => {
    window.localStorage.setItem("forge.watch.insightsApp.p1", "http://localhost:3001");
    window.localStorage.setItem("forge.watch.insightsApp.other", "tunnel");
    await mount();
    await click(button(/^Insights$/));
    expect(q("insights-stub")!.getAttribute("data-app")).toBe("http://localhost:3001");
  });

  it("goes to Watch live from the page's own Open Watch live", async () => {
    await mount();
    await click(button(/^Insights$/));
    await click(button(/stub-open-watch/));
    expect(q("insights-stub")).toBeNull();
    expect(q("watch-stub")).not.toBeNull();
    expect(button(/Watch live/).getAttribute("aria-pressed")).toBe("true");
  });
});
