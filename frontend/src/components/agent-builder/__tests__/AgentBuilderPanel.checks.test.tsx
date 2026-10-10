/**
 * AgentBuilderPanel — what is wrong with the agent is said before Apply.
 *
 * The check runs a moment after the drawing stops changing and again when Apply is pressed. A problem
 * that will stop a tool working is shown and asked about ("Apply anyway?") before anything is
 * installed; warnings and notes never block; a check that itself fails never blocks Apply.
 *
 * jsdom + manual createRoot + act() — same house style as AgentBuilderPanel.save.test.tsx.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
if (typeof window !== "undefined" && !(window as any).DOMMatrixReadOnly) {
  (window as any).DOMMatrixReadOnly = class {
    m22 = 1;
    constructor(_: unknown) {}
  };
}
if (typeof window !== "undefined" && !(window as any).matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  })) as unknown as typeof window.matchMedia;
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

const apiGet = vi.fn(async (_url: string) => []);
const apiPost = vi.fn(async (_url: string, _body?: unknown): Promise<unknown> => ({ saved: true }));

vi.mock("@/lib/api", () => ({
  api: {
    get: (url: string) => apiGet(url),
    post: (url: string, body?: unknown) => apiPost(url, body),
    put: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

import { AgentBuilderPanel } from "../AgentBuilderPanel";
import { useAgentBuilderStore } from "@/stores/agent-builder";

let container: HTMLDivElement;
let root: Root;
let fetchSpy: ReturnType<typeof vi.fn>;
const unhandled: unknown[] = [];
const onUnhandled = (e: unknown) => unhandled.push(e);

beforeEach(() => {
  apiGet.mockClear();
  apiPost.mockReset();
  apiPost.mockResolvedValue({ saved: true });
  useAgentBuilderStore.getState().setCurrentAgent(null);
  fetchSpy = vi.fn();
  (globalThis as any).fetch = fetchSpy;
  unhandled.length = 0;
  process.on("unhandledRejection", onUnhandled);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  process.off("unhandledRejection", onUnhandled);
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

const FINDINGS = [
  { severity: "error", code: "unknown_workflow", message: "Tool 'refund' runs a workflow this app does not have.", nodeId: "tool_1" },
  { severity: "warning", code: "tool_unimplemented", message: "Tool 'recommend' has no code yet.", nodeId: "tool_2" },
  { severity: "info", code: "handoff_not_running", message: "Human handoff is saved but does not run yet.", nodeId: "handoff_1" },
];
const WARNINGS_ONLY = FINDINGS.slice(1);

function checkReturns(findings: unknown[], appChecked = true) {
  apiPost.mockImplementation(async (url: string) =>
    String(url).endsWith("/check") ? { findings, appChecked } : { saved: true });
}

async function mountEditor() {
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
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });
  const newAgent = [...container.querySelectorAll("button")].find((b) => /New Agent/.test(b.textContent ?? ""))!;
  await act(async () => {
    newAgent.click();
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

const button = (label: RegExp) =>
  [...container.querySelectorAll("button")].find((b) => label.test(b.textContent ?? ""))!;

async function click(el: Element, wait = 30) {
  await act(async () => {
    (el as HTMLButtonElement).click();
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, wait));
  });
}

const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
const bar = () => container.querySelector('[data-testid="agent-checks"]');
const checkCalls = () => apiPost.mock.calls.filter(([url]) => String(url).endsWith("/check"));
const SSE_DONE = { ok: true, body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) } };

describe("AgentBuilderPanel — checks before Apply", () => {
  it("says what is wrong a moment after the drawing settles, with counts", async () => {
    checkReturns(FINDINGS);
    await mountEditor();
    await wait(1000);
    expect(checkCalls().length).toBeGreaterThanOrEqual(1);
    expect(checkCalls()[0][0]).toBe("/api/projects/p1/agent-definitions/check");
    expect(bar()?.textContent).toContain("Checks: 1 problem · 1 warning · 1 note");
    expect(unhandled).toEqual([]);
  });

  it("lists each finding and Show selects the box it is about", async () => {
    checkReturns(FINDINGS);
    await mountEditor();
    await wait(1000);
    await click(bar()!.querySelector("button")!); // expand
    expect(bar()?.textContent).toContain("runs a workflow this app does not have");
    const show = [...bar()!.querySelectorAll("button")].filter((b) => b.textContent === "Show");
    expect(show.length).toBe(3);
    await click(show[0]);
    expect(useAgentBuilderStore.getState().selectedNodeId).toBe("tool_1");
  });

  it("a clean agent says so", async () => {
    checkReturns([]);
    await mountEditor();
    await wait(1000);
    expect(bar()?.textContent).toContain("No problems found, checked against this app.");
  });

  it("with no built app it says only the agent was checked", async () => {
    checkReturns([], false);
    await mountEditor();
    await wait(1000);
    expect(bar()?.textContent).toMatch(/no built app yet/);
  });

  it("Apply with a problem asks first and installs nothing until you say so", async () => {
    checkReturns(FINDINGS);
    fetchSpy.mockResolvedValue(SSE_DONE);
    await mountEditor();
    await click(button(/Apply/), 60);
    expect(bar()?.textContent).toContain("1 problem will stop some of the tools from working. Apply anyway?");
    expect(fetchSpy).not.toHaveBeenCalled();

    await click(button(/Apply anyway/), 60);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(String(fetchSpy.mock.calls[0][0])).toMatch(/\/agent-definitions\/.+\/apply$/);
    expect(bar()?.textContent).not.toContain("Apply anyway?");
  });

  it("Cancel drops the question and installs nothing", async () => {
    checkReturns(FINDINGS);
    fetchSpy.mockResolvedValue(SSE_DONE);
    await mountEditor();
    await click(button(/Apply/), 60);
    await click(button(/^Cancel$/), 30);
    expect(bar()?.textContent).not.toContain("Apply anyway?");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("warnings and notes never block Apply", async () => {
    checkReturns(WARNINGS_ONLY);
    fetchSpy.mockResolvedValue(SSE_DONE);
    await mountEditor();
    await click(button(/Apply/), 60);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(bar()?.textContent).not.toContain("Apply anyway?");
  });

  it("a check that fails never blocks Apply", async () => {
    apiPost.mockImplementation(async (url: string) => {
      if (String(url).endsWith("/check")) throw new Error("check is down");
      return { saved: true };
    });
    fetchSpy.mockResolvedValue(SSE_DONE);
    await mountEditor();
    await click(button(/Apply/), 60);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(unhandled).toEqual([]);
  });
});
