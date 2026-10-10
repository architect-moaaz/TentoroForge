/**
 * AgentBuilderPanel — "Suggest from my app".
 *
 * The builder used to start from generic templates. The suggest button asks the platform to draw an
 * agent from THIS app's Blueprint and puts it on the canvas to edit, save and Apply. A project with no
 * Blueprint yet answers in words, and the list view stays where it is.
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

async function mountList() {
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
}

const buttons = (label: RegExp) =>
  [...container.querySelectorAll("button")].filter((b) => label.test(b.textContent ?? ""));

async function click(el: Element) {
  await act(async () => {
    (el as HTMLButtonElement).click();
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 30));
  });
}

const SUGGESTED = {
  id: "app_assistant",
  name: "Movie Review Assistant",
  description: "Answers questions about Movie Review.",
  nodes: [
    {
      id: "sp_1",
      type: "system_prompt",
      position: { x: 40, y: 100 },
      data: { label: "Movie Review assistant", nodeType: "system_prompt", config: { prompt: "You are the assistant for Movie Review.", is_entry_point: true } },
    },
  ],
  edges: [],
};

describe("AgentBuilderPanel — suggest an agent from the app", () => {
  it("asks the platform for this project's suggestion and opens it in the editor", async () => {
    apiPost.mockResolvedValueOnce(SUGGESTED);
    await mountList();
    await click(buttons(/Suggest from my app/)[0]);

    expect(apiPost).toHaveBeenCalledWith("/api/projects/p1/agent-definitions/suggest", {});
    const name = container.querySelector("input") as HTMLInputElement;
    expect(name.value).toBe("Movie Review Assistant");
    expect(useAgentBuilderStore.getState().currentAgent?.id).toBe("app_assistant");
    // a suggestion is only a draft: nothing was saved
    expect(apiPost.mock.calls.filter(([url]) => !String(url).endsWith("/suggest"))).toEqual([]);
    expect(unhandled).toEqual([]);
  });

  it("the empty list offers it too, ahead of the generic templates", async () => {
    await mountList();
    const all = buttons(/Suggest from my app/);
    expect(all.length).toBe(2); // the header button and the empty-state card
    const templates = container.textContent ?? "";
    expect(templates.indexOf("Suggest from my app")).toBeLessThan(templates.indexOf("Start from a template"));
  });

  it("a project with no Blueprint yet says so and stays on the list", async () => {
    apiPost.mockRejectedValueOnce(new Error("This project has no Blueprint yet — build the app first, then suggest an agent for it."));
    await mountList();
    await click(buttons(/Suggest from my app/)[0]);

    expect(container.querySelector('[role="alert"]')?.textContent).toMatch(/build the app first/);
    expect(useAgentBuilderStore.getState().currentAgent).toBeNull();
    expect(unhandled).toEqual([]);
  });
});
