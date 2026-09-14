/**
 * REPRO part 2 — the responsive value COMMITS (proved in repro-breakpoint-props),
 * so the question is what the user actually sees afterwards:
 *
 *   A. does the Engine render the sm override at all?
 *   B. what does the Properties panel show for a prop at a bp with no
 *      override yet (readPropAtBp returns undefined by design)?
 *   C. does the editor CANVAS change its viewport when you pick a breakpoint,
 *      or does the switcher only change which value you are editing?
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import React from "react";
import { Engine, EngineProvider, pickResponsiveValue } from "@tentoroforge/engine";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  // @ts-expect-error minimal polyfill
  window.matchMedia = (q: string) => ({ matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {}, addEventListener() {},
    removeEventListener() {}, dispatchEvent() { return false; } });
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}

const NAV_FLOW = {
  version: "1.0", initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [], guards: {},
};

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

async function render(page: any) {
  await act(async () => {
    root.render(
      <EngineProvider designSpec={{}} navFlow={NAV_FLOW as any} cssVarTokens={{}}>
        <Engine schema={page} previewData={{}} />
      </EngineProvider>,
    );
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
}
const page = (props: any) => ({
  schemaVersion: "2", id: "home", route: "/",
  root: { id: "root", type: "Container", props: {},
          children: [{ id: "n1", type: "Input", props, children: [] }] },
});

describe("REPRO — does an sm override reach the DOM?", () => {
  it("A. renders the responsive label override", async () => {
    await render(page({ name: "email", label: "PLAIN_LABEL" }));
    const plain = container.querySelector('[data-node-id="n1"]')?.textContent ?? "";

    await render(page({ name: "email", label: { default: "BASE_LABEL", sm: "SM_LABEL" } }));
    const resp = container.querySelector('[data-node-id="n1"]')?.textContent ?? "";

    console.log(`[BP-RENDER] jsdom window.innerWidth = ${window.innerWidth}`);
    console.log(`[BP-RENDER] plain label   → ${JSON.stringify(plain)}`);
    console.log(`[BP-RENDER] responsive    → ${JSON.stringify(resp)}`);
    console.log(`[BP-RENDER] shows BASE? ${resp.includes("BASE_LABEL")}  shows SM? ${resp.includes("SM_LABEL")}`);
    console.log(`[BP-RENDER] raw object leaked into DOM? ${resp.includes("[object") || resp.includes("default")}`);
    expect(typeof resp).toBe("string");
  });

  it("B. pickResponsiveValue cascade at each breakpoint", () => {
    const v = { default: "BASE", sm: "SM" };
    for (const bp of ["default", "sm", "md", "lg", "xl"] as const) {
      console.log(`[BP-CASCADE] at ${bp.padEnd(7)} → ${JSON.stringify(pickResponsiveValue(v, bp))}`);
    }
    // A value set ONLY at lg, viewed at sm — should fall back to default.
    const v2 = { default: "BASE", lg: "LG" };
    for (const bp of ["sm", "lg"] as const) {
      console.log(`[BP-CASCADE-2] {default,lg} at ${bp.padEnd(4)} → ${JSON.stringify(pickResponsiveValue(v2, bp))}`);
    }
    expect(true).toBe(true);
  });
});
