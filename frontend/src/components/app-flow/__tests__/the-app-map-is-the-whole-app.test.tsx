/**
 * Pages & Nav drew the screens and App Flow drew only the screens a path
 * touched. The App Map draws both: every screen, how a person reaches it,
 * the paths, and what nothing reaches (Mark 8's tax page, 2026-10-17).
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
  (window as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

let response: any;
vi.mock("@/lib/api", () => ({
  api: { get: async () => { if (response instanceof Error) throw response; return response; } },
}));
vi.mock("@/components/navigation/NavigationPanel", () => ({ NavigationPanel: () => <div>old screen editor</div> }));

import { AppFlowPanel } from "../AppFlowPanel";

let root: Root;
let host: HTMLDivElement;
async function render() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => { root.render(<QueryClientProvider client={qc}><div style={{ width: 1200, height: 800 }}><AppFlowPanel projectId="p1" /></div></QueryClientProvider>); });
  for (let i = 0; i < 12; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

const flow = { id: "J1", name: "Compute a Calculation", role: "Everyone", goal: "A result", ends: "The result shows.",
  nodes: [{ id: "s0", page: "PAGE-001", screen: "Calculator", route: "/", part: "", placement: "", last: false },
          { id: "s1", page: "PAGE-001", screen: "Calculator", route: "/", part: "Result", placement: "panel", last: true }],
  edges: [{ from: "s0", to: "s1", does: "types a sum", process: "", then: "go" }] };
const screen = (id: string, name: string, route: string, extra: object = {}) =>
  ({ id, name, route, purpose: "", pattern: "tool", access: "authenticated", who: [], menu: "", landing: [], entry: false, flows: [], starts: [], ...extra });

beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("the App Map", () => {
  it("draws every screen, how people reach it, and names what no path reaches", async () => {
    response = { flows: [flow], findings: [], map: {
      screens: [screen("PAGE-001", "Calculator", "/", { menu: "Calculator", flows: ["Compute a Calculation"] }),
                screen("PAGE-003", "Tax", "/tax", { menu: "Tax" }),
                screen("PAGE-004", "Onboarding", "/onboarding", { afterSignup: true })],
      links: [{ from: "PAGE-001", to: "PAGE-003" }], menu: [],
      gaps: [{ kind: "no_path", page: "PAGE-003", text: "Tax (/tax) — no path anyone takes passes through it" }] } };
    await render();
    const text = document.body.textContent ?? "";
    expect(text).toContain("App Map");
    expect(text).toContain("3 screens · 1 path");
    // The screen no path touches is on the map, with its menu entry and its gap.
    expect(text).toContain("Tax");
    expect(text).toContain("on no path");
    expect(text).toContain("after sign-up");
    expect(text).toContain("1 screen people may not find");
    // The list is folded at first; opening it names each screen.
    expect(text).not.toContain("Tax (/tax) — no path anyone takes passes through it");
    const strip = [...document.body.querySelectorAll("[data-map-gaps] button")][0] as HTMLButtonElement;
    await act(async () => { strip.click(); });
    expect(document.body.textContent).toContain("Tax (/tax) — no path anyone takes passes through it");
  });

  it("draws the screens even before any path is written", async () => {
    response = { flows: [], findings: [], map: { screens: [screen("PAGE-001", "Calculator", "/")], links: [], menu: [], gaps: [] } };
    await render();
    expect(document.body.textContent).toContain("1 screen · 0 paths");
    expect(document.body.textContent).not.toContain("No app flow yet");
  });

  it("keeps the old screen editor for a project with no Blueprint", async () => {
    response = new Error("404");
    await render();
    expect(document.body.textContent).toContain("old screen editor");
  });
});
