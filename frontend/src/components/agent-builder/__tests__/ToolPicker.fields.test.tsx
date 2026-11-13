/**
 * "Fields the assistant can see" on a tool: the setting Find problems can change with a fix ("Show fewer fields"), so it has to
 * be visible and editable where the builder looks for a tool's settings, and a fix applied or taken back out shows up in it.
 *
 * Typed as words with commas and kept as a list: a comma and a space being typed must not be rubbed out by the list they make.
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

import { ToolPicker } from "../config/ToolPicker";
import type { ToolConfig } from "@/types/agent-builder";

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

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const picker = (config: ToolConfig, onUpdate: (u: Partial<ToolConfig>) => void) => (
  <QueryClientProvider client={qc}>
    <ToolPicker config={config} onUpdate={onUpdate} projectId="p" orgId="o" />
  </QueryClientProvider>
);
async function render(config: ToolConfig, onUpdate: (u: Partial<ToolConfig>) => void = () => {}) {
  await act(async () => { root.render(picker(config, onUpdate)); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
const field = () => container.querySelector("#tool-fields") as HTMLInputElement;
const type = (value: string) =>
  act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field(), value);
    field().dispatchEvent(new Event("input", { bubbles: true }));
  });
const text = () => container.textContent ?? "";

describe("Fields the assistant can see", () => {
  it("starts empty with the words that say what empty means, and that credentials are always removed", async () => {
    await render({ tool_type: "data_engine", entity: "tickets", operation: "list" });
    expect(container.querySelector('label[for="tool-fields"]')?.textContent).toBe("Fields the assistant can see");
    expect(field().value).toBe("");
    expect(field().placeholder).toBe("Everything the app returns");
    expect(text()).toContain("Passwords, keys and tokens are always removed");
  });

  it("shows the fields a tool already has, as words, and says the others are hidden", async () => {
    await render({ tool_type: "data_engine", entity: "tickets", operation: "list", response_filter: ["id", "subject", "status"] });
    expect(field().value).toBe("id, subject, status");
    expect(text()).toContain("Any other field of the tool's answer is hidden from the assistant");
  });

  it("turns what is typed into a list, trimmed and without blanks or repeats, and an empty box into no list at all", async () => {
    const update = vi.fn();
    await render({ tool_type: "data_engine", entity: "tickets", operation: "list" }, update);
    await type("id, subject ,, id,  status ");
    expect(update).toHaveBeenLastCalledWith({ response_filter: ["id", "subject", "status"] });
    await type("");
    expect(update).toHaveBeenLastCalledWith({ response_filter: undefined });
  });

  it("does not rub out a comma and a space while they are being typed", async () => {
    let config: ToolConfig = { tool_type: "data_engine", entity: "tickets", operation: "list" };
    const update = (u: Partial<ToolConfig>) => { config = { ...config, ...u }; };
    await render(config, update);
    await type("id, ");
    await act(async () => { root.render(picker(config, update)); });
    expect(field().value, "the list is [id] but the words are still being typed").toBe("id, ");
    await type("id, sub");
    await act(async () => { root.render(picker(config, update)); });
    expect(field().value).toBe("id, sub");
    expect(config.response_filter).toEqual(["id", "sub"]);
  });

  it("follows the tool when something else changes it: a fix from Find problems, or taking it back out", async () => {
    await render({ tool_type: "data_engine", entity: "tickets", operation: "list" });
    expect(field().value).toBe("");
    await act(async () => { root.render(picker({ tool_type: "data_engine", entity: "tickets", operation: "list", response_filter: ["id", "subject"] }, () => {})); });
    expect(field().value).toBe("id, subject");
    await act(async () => { root.render(picker({ tool_type: "data_engine", entity: "tickets", operation: "list" }, () => {})); });
    expect(field().value, "undone: back to everything").toBe("");
  });
});
