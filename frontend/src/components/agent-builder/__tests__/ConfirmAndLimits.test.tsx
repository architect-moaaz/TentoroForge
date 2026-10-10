/**
 * The two safety settings in the builder: "Ask the person first" on a tool, and the usage limits on the guardrail.
 *
 * A tool that changes data starts with the switch ON (and says the app enforces it); a read starts OFF; the builder
 * can flip either, and turning a write OFF says plainly what that means. The limits are three numbers: empty uses
 * the usual limit, 0 means none. jsdom + manual createRoot + act().
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  })) as unknown as typeof window.matchMedia;
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (typeof window !== "undefined" && !(window as any).PointerEvent) (window as any).PointerEvent = class extends Event {} as any;
if (typeof Element !== "undefined" && !(Element.prototype as any).hasPointerCapture) {
  (Element.prototype as any).hasPointerCapture = () => false;
  (Element.prototype as any).releasePointerCapture = () => {};
  (Element.prototype as any).setPointerCapture = () => {};
  (Element.prototype as any).scrollIntoView = () => {};
}

vi.mock("@/lib/api", () => ({ api: { get: vi.fn(async () => []), post: vi.fn(), put: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }));

import { ToolPicker, changesData } from "../config/ToolPicker";
import { GuardrailEditor } from "../config/GuardrailEditor";
import type { GuardrailConfig, ToolConfig } from "@/types/agent-builder";

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function renderTool(config: ToolConfig, onUpdate: (u: Partial<ToolConfig>) => void) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={qc}>
        <ToolPicker config={config} onUpdate={onUpdate} projectId="p" orgId="o" />
      </QueryClientProvider>,
    );
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

const sw = () => container.querySelector('[aria-label="Ask the person first"]') as HTMLElement;
const text = () => container.textContent ?? "";

describe("changesData", () => {
  it("is true for writes and workflows, false for reads and unknowns", () => {
    expect(changesData({ tool_type: "data_engine", operation: "update" })).toBe(true);
    expect(changesData({ tool_type: "data_engine", operation: "create" })).toBe(true);
    expect(changesData({ tool_type: "data_engine", operation: "delete" })).toBe(true);
    expect(changesData({ tool_type: "data_engine", operation: "list" })).toBe(false);
    expect(changesData({ tool_type: "data_engine", operation: "get" })).toBe(false);
    expect(changesData({ tool_type: "workflow" })).toBe(true);
    expect(changesData({ tool_type: "api_call", method: "POST" })).toBe(true);
    expect(changesData({ tool_type: "api_call", method: "get" })).toBe(false);
    expect(changesData({ tool_type: "api_call" })).toBe(false);
    expect(changesData({ tool_type: "function" })).toBe(false);
    expect(changesData({ tool_type: "mcp" })).toBe(false);
  });
});

describe("Ask the person first", () => {
  it("is on for a tool that changes data, and says the app enforces it", async () => {
    await renderTool({ tool_type: "data_engine", entity: "tickets", operation: "update" }, () => {});
    expect(sw().getAttribute("aria-checked")).toBe("true");
    expect(text()).toContain("The app enforces this");
  });

  it("is off for a read, which runs straight away", async () => {
    await renderTool({ tool_type: "data_engine", entity: "tickets", operation: "list" }, () => {});
    expect(sw().getAttribute("aria-checked")).toBe("false");
    expect(text()).toContain("Reads run straight away");
  });

  it("can be switched off for a write, with the consequence spelled out, and on for anything", async () => {
    const update = vi.fn();
    await renderTool({ tool_type: "data_engine", entity: "tickets", operation: "update" }, update);
    await act(async () => { sw().click(); });
    expect(update).toHaveBeenLastCalledWith({ confirm: false });

    await act(async () => root.unmount());
    root = createRoot(container);
    await renderTool({ tool_type: "data_engine", entity: "tickets", operation: "update", confirm: false }, update);
    expect(sw().getAttribute("aria-checked")).toBe("false");
    expect(text()).toContain("will run as soon as the assistant decides to");

    await act(async () => root.unmount());
    root = createRoot(container);
    await renderTool({ tool_type: "function" }, update);
    await act(async () => { sw().click(); });
    expect(update).toHaveBeenLastCalledWith({ confirm: true });
  });
});

describe("Usage limits", () => {
  const input = (label: string) => container.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
  async function renderGuard(config: GuardrailConfig, onUpdate: (u: Partial<GuardrailConfig>) => void) {
    await act(async () => { root.render(<GuardrailEditor config={config} onUpdate={onUpdate} />); });
  }
  async function type(el: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => {
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  it("shows the usual limits in grey and the set ones as values", async () => {
    await renderGuard({ max_messages_per_hour: 40 }, () => {});
    expect(input("messages a minute").placeholder).toBe("12");
    expect(input("messages an hour").value).toBe("40");
    expect(input("model tokens a day").placeholder).toBe("500000");
    expect(container.textContent).toContain("0 means no limit");
  });

  it("writes a number, keeps 0 (no limit), and clears an empty box back to the usual", async () => {
    const update = vi.fn();
    await renderGuard({}, update);
    await type(input("messages a minute"), "5");
    expect(update).toHaveBeenLastCalledWith({ max_messages_per_minute: 5 });
    await type(input("messages an hour"), "0");
    expect(update).toHaveBeenLastCalledWith({ max_messages_per_hour: 0 });
    await renderGuard({ max_tokens_per_day: 100 }, update);
    await type(input("model tokens a day"), "");
    expect(update).toHaveBeenLastCalledWith({ max_tokens_per_day: undefined });
    await type(input("messages a minute"), "-3");
    expect(update).toHaveBeenLastCalledWith({ max_messages_per_minute: undefined });
  });
});
