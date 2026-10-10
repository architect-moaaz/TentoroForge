/**
 * AgentBuilderPanel — what a failed Save / Apply looks like.
 *
 * Save used to be called straight from a click handler, so a server error
 * (a project whose folder was missing answered FileNotFoundError) escaped as an
 * uncaught "Runtime ApiError" overlay with nowhere to go. The outcome belongs in
 * the status bar, in words, and Apply must not go on to call the server after a
 * save that did not happen.
 *
 * jsdom + manual createRoot + act() — same house style as ToolPicker.mcp.test.tsx.
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
  // The list view's "New Agent" opens a blank agent in the editor.
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

async function click(el: Element) {
  await act(async () => {
    (el as HTMLButtonElement).click();
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

describe("AgentBuilderPanel — a failed save is reported, not thrown", () => {
  it("Save shows the server's words in the status bar", async () => {
    apiPost.mockRejectedValueOnce(new Error("FileNotFoundError: the project folder is missing"));
    await mountEditor();
    await click(button(/^\s*Save\s*$/));

    const bar = container.querySelector('[role="status"]');
    expect(bar?.textContent).toBe("Error: FileNotFoundError: the project folder is missing");
    expect(bar?.className).toMatch(/red/);
    expect(unhandled).toEqual([]);
  });

  it("Apply stops at a failed save and never calls the server's apply", async () => {
    apiPost.mockRejectedValueOnce(new Error("could not save"));
    await mountEditor();
    await click(button(/Apply/));

    expect(container.querySelector('[role="status"]')?.textContent).toBe("Error: could not save");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(unhandled).toEqual([]);
  });

  it("a good save says so", async () => {
    await mountEditor();
    await click(button(/^\s*Save\s*$/));
    const bar = container.querySelector('[role="status"]');
    expect(bar?.textContent).toBe("Saved.");
    expect(bar?.className).not.toMatch(/red/);
  });

  it("the server's final message stays visible after Apply finishes", async () => {
    const encoder = new TextEncoder();
    const sse =
      'event: error\ndata: {"message":"This project has no generated app yet. Your agent is saved and will be installed when the app is built."}\n\n';
    fetchSpy.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => {
          let sent = false;
          return {
            read: async () =>
              sent ? { done: true, value: undefined } : ((sent = true), { done: false, value: encoder.encode(sse) }),
          };
        },
      },
    });
    await mountEditor();
    await click(button(/Apply/));

    // Apply has finished (the spinner is gone) and the message is still there to read.
    expect(container.querySelector('[role="status"]')?.textContent).toContain("no generated app yet");
    expect(button(/Apply/).hasAttribute("disabled")).toBe(false);
  });

  it("opening the list again clears the last message", async () => {
    apiPost.mockRejectedValueOnce(new Error("boom"));
    await mountEditor();
    await click(button(/^\s*Save\s*$/));
    expect(container.querySelector('[role="status"]')).not.toBeNull();

    // back to the list, then into a new agent
    const back = container.querySelector("button svg.lucide-arrow-left")?.closest("button") as HTMLButtonElement;
    await click(back);
    await click(button(/New Agent/));
    expect(container.querySelector('[role="status"]')).toBeNull();
  });
});
