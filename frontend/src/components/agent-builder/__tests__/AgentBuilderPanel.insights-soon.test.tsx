/**
 * AgentBuilderPanel: Insights says "Coming soon" while it is not open.
 *
 * The page is built and kept (its own tests, and the wiring tests in AgentBuilderPanel.insights.test.tsx, which switch the flag on). With the
 * flag off, as it ships: the toolbar button carries a Soon badge, pressing it shows the Coming soon page and NOT the real one, the page asks
 * the server for nothing, and the other pages and the Diagram button still take the person away from it.
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


describe("Insights is coming soon", () => {
  it("marks the button Soon, and pressing it shows the Coming soon page and not the real one", async () => {
    await mount();
    const insights = button(/^Insights/);
    expect(insights.textContent, "the toolbar says so").toMatch(/Soon/i);
    expect(q("insights-coming-soon")).toBeNull();
    await click(insights);
    const page = q("insights-coming-soon");
    expect(page?.textContent).toContain("Coming soon");
    expect(page?.textContent).toContain("Insights");
    expect(q("insights-stub"), "the real page is not offered").toBeNull();
    expect(insights.getAttribute("aria-pressed")).toBe("true");
  });

  it("asks the server for no insights while it is coming soon", async () => {
    await mount();
    await click(button(/^Insights/));
    expect(apiGet.mock.calls.map((c) => String(c[0])).filter((u) => /insights/i.test(u))).toEqual([]);
  });

  it("the Diagram button takes the person back to the drawing, and pressing Insights again puts it away", async () => {
    await mount();
    await click(button(/^Insights/));
    expect(q("insights-coming-soon")).not.toBeNull();
    await click(button(/^Diagram$/));
    expect(q("insights-coming-soon")).toBeNull();
    await click(button(/^Insights/));
    await click(button(/^Insights/));
    expect(q("insights-coming-soon"), "a second press closes it").toBeNull();
  });

  it("the other pages close it, as they close the real one", async () => {
    await mount();
    for (const other of [/Find problems/, /^Test$/]) {
      await click(button(/^Insights/));
      expect(q("insights-coming-soon"), "open").not.toBeNull();
      await click(button(other));
      expect(q("insights-coming-soon"), `${other} closes it`).toBeNull();
      await click(button(other)); // put that page away again
    }
  });

  it("the other Soon page is unaffected: Watch live still opens its real page", async () => {
    await mount();
    await click(button(/Watch live/));
    expect(q("watch-stub"), "Watch live is open").not.toBeNull();
    expect(q("insights-coming-soon")).toBeNull();
  });
});
