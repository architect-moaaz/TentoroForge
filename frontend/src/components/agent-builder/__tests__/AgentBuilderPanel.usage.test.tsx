/**
 * The Agents tab and workflows: an assistant that workflows use says "Used by N workflows", one made for a workflow
 * carries a quiet tag, and deleting one that is in use asks first and names the workflows.
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
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (typeof window !== "undefined" && !(window as any).DOMMatrixReadOnly) {
  (window as any).DOMMatrixReadOnly = class { m22 = 1; constructor(_: unknown) {} };
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

const BASE = "/api/projects/p1/agent-definitions";
const LIST = [
  { id: "wf_handle_request_triage", name: "Triage", description: "Works out how urgent a request is", node_count: 4 },
  { id: "vet_chat", name: "Vet helper", description: "Answers owners", node_count: 5 },
  { id: "plain_one", name: "Plain one", description: null, node_count: 2 },
];
const USED: Record<string, unknown> = {
  wf_handle_request_triage: {
    workflows: [
      { workflowId: "wf_a", workflowName: "Handle appointment request", stepId: "agent_step_1" },
      { workflowId: "wf_a", workflowName: "Handle appointment request", stepId: "agent_step_2" },
      { workflowId: "wf_b", workflowName: "Reminders", stepId: "agent_step_1" },
    ],
  },
  vet_chat: { workflows: [{ workflowId: "wf_c", workflowName: "Walk-in intake", stepId: "agent_step_9" }] },
  plain_one: { workflows: [] },
};

const apiGet = vi.fn(async (_url: string): Promise<unknown> => []);
const apiDelete = vi.fn(async (_url: string): Promise<unknown> => undefined);
vi.mock("@/lib/api", () => ({
  api: {
    get: (url: string) => apiGet(url),
    post: vi.fn(),
    put: vi.fn(),
    delete: (url: string) => apiDelete(url),
  },
  ApiError: class ApiError extends Error {},
}));

import { AgentBuilderPanel } from "../AgentBuilderPanel";
import { useAgentBuilderStore } from "@/stores/agent-builder";

let container: HTMLDivElement;
let root: Root;

function serve(opts: { usedByRoute?: "present" | "missing" | "broken" } = {}) {
  const route = opts.usedByRoute ?? "present";
  apiGet.mockImplementation(async (url: string) => {
    if (url === BASE) return LIST;
    const m = url.match(/^\/api\/projects\/p1\/agent-definitions\/([^/]+)\/used-by$/);
    if (m) {
      if (route === "missing") throw Object.assign(new Error("Not Found"), { status: 404 });
      if (route === "broken") return "<html>not json</html>";
      return USED[decodeURIComponent(m[1])] ?? { workflows: [] };
    }
    return [];
  });
}

beforeEach(() => {
  apiGet.mockReset();
  apiDelete.mockReset();
  apiDelete.mockResolvedValue(undefined);
  useAgentBuilderStore.getState().setCurrentAgent(null);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const wait = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
async function mountList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={qc}>
        <div style={{ width: 700, height: 600 }}><AgentBuilderPanel projectId="p1" /></div>
      </QueryClientProvider>,
    );
  });
  await wait(60);
}
const row = (name: string) =>
  [...container.querySelectorAll("div.cursor-pointer")].find((r) => r.textContent?.includes(name)) as HTMLElement;
const deleteButton = (name: string) => row(name).querySelector(`button[aria-label="Delete ${name}"]`) as HTMLButtonElement;
const dialog = () => document.body.querySelector('[role="dialog"]') as HTMLElement | null;
const dialogButton = (re: RegExp) => [...(dialog()?.querySelectorAll("button") ?? [])].find((b) => re.test(b.textContent ?? "")) as HTMLButtonElement;
async function click(el: Element) {
  await act(async () => { (el as HTMLElement).click(); });
  await wait(30);
}

describe("Agents tab: assistants that workflows use", () => {
  it("says how many different workflows use an assistant (two steps in one workflow count once)", async () => {
    serve();
    await mountList();
    expect(row("Triage").textContent).toContain("Used by 2 workflows");
    expect(row("Vet helper").textContent).toContain("Used by 1 workflow");
    expect(row("Vet helper").textContent).not.toContain("Used by 1 workflows");
    expect(row("Plain one").textContent).not.toContain("Used by");
    expect(apiGet).toHaveBeenCalledWith(`${BASE}/wf_handle_request_triage/used-by`);
  });

  it("tags only the assistants made for a workflow, quietly", async () => {
    serve();
    await mountList();
    expect(row("Triage").textContent).toContain("Made for a workflow");
    expect(row("Vet helper").textContent).not.toContain("Made for a workflow");
    expect(row("Plain one").textContent).not.toContain("Made for a workflow");
  });

  it("shows nothing, and no error, when the platform has no used-by route (404) or answers oddly", async () => {
    for (const usedByRoute of ["missing", "broken"] as const) {
      serve({ usedByRoute });
      await mountList();
      expect(row("Triage").textContent).not.toContain("Used by");
      expect(row("Triage").textContent).toContain("Made for a workflow");
      expect(container.querySelector('[role="alert"]')).toBeNull();
      act(() => root.unmount());
      root = createRoot(container);
    }
  });

  it("deletes an assistant nothing uses at once, as before", async () => {
    serve();
    await mountList();
    await click(deleteButton("Plain one"));
    expect(dialog()).toBeNull();
    expect(apiDelete).toHaveBeenCalledWith(`${BASE}/plain_one`);
  });

  it("asks first when workflows use it, naming each one, and deletes nothing until told", async () => {
    serve();
    await mountList();
    await click(deleteButton("Triage"));
    expect(apiDelete).not.toHaveBeenCalled();
    const d = dialog()!;
    expect(d).toBeTruthy();
    expect(d.textContent).toContain("Delete this assistant?");
    expect(d.textContent).toContain("Triage is used by 2 workflows");
    const items = [...d.querySelectorAll('[data-testid="used-by-list"] li')].map((li) => li.textContent);
    expect(items).toEqual([
      "Handle appointment request, step agent_step_1",
      "Handle appointment request, step agent_step_2",
      "Reminders, step agent_step_1",
    ]);
    // the row behind did not open the assistant
    expect(useAgentBuilderStore.getState().currentAgent).toBeNull();

    await click(dialogButton(/Keep it/));
    expect(apiDelete).not.toHaveBeenCalled();
    expect(dialog()).toBeNull();
  });

  it("deletes it after the person says so", async () => {
    serve();
    await mountList();
    await click(deleteButton("Vet helper"));
    expect(dialog()!.textContent).toContain("Vet helper is used by 1 workflow.");
    await click(dialogButton(/Delete it anyway/));
    expect(apiDelete).toHaveBeenCalledWith(`${BASE}/vet_chat`);
    expect(dialog()).toBeNull();
  });

  it("asks fresh at delete time, in case a workflow picked the assistant since the list was drawn", async () => {
    serve();
    await mountList();
    const before = apiGet.mock.calls.filter((c) => String(c[0]).endsWith("/plain_one/used-by")).length;
    USED.plain_one = { workflows: [{ workflowId: "wf_z", workflowName: "Brand new", stepId: "s" }] };
    try {
      await click(deleteButton("Plain one"));
      expect(apiGet.mock.calls.filter((c) => String(c[0]).endsWith("/plain_one/used-by")).length).toBe(before + 1);
      expect(dialog()!.textContent).toContain("Brand new");
      expect(apiDelete).not.toHaveBeenCalled();
    } finally {
      USED.plain_one = { workflows: [] };
    }
  });

  it("gives the delete buttons and the dialog no brackets or ampersands", async () => {
    serve();
    await mountList();
    await click(deleteButton("Triage"));
    const names = [...container.querySelectorAll("button"), ...(dialog()?.querySelectorAll("button") ?? [])].flatMap((b) => [
      b.textContent ?? "",
      b.getAttribute("aria-label") ?? "",
    ]);
    for (const n of names) expect(n).not.toMatch(/[\[\]{}()<>&]/);
  });
});
