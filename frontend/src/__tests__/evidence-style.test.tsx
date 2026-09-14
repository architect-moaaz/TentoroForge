/**
 * EVIDENCE — what does the DOM ACTUALLY carry after a Style-tab edit?
 *
 * Tier 1 reported padding/radius/shadow/background as NOT-OBSERVED on 124 of
 * 129 components while all six size keys applied on 129/129. Before that can be
 * called a defect it has to survive the obvious alternative: that my assertion
 * is too strict. `EngineProvider` emits every token var TWICE (`--<g>-<p>` and
 * `--token-<g>-<p>`), and three different functions named `resolveStyle` exist
 * in this repo — so the component could be emitting a correct-but-differently-
 * spelled value that an exact string match would miss.
 *
 * This prints the raw style attribute and outerHTML instead of asserting, so
 * the verdict is read off evidence rather than inferred from a boolean.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import React from "react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { buildDroppedNode } from "@/components/canvas/hooks/useDrop";
import { useEditorStore } from "@/lib/editor-store";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  // @ts-expect-error minimal polyfill
  window.matchMedia = (q: string) => ({
    matches: false, media: q, onchange: null, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  });
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}

const NAV_FLOW = {
  version: "1.0", initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [], guards: {},
};
const EMPTY_TOKENS = { color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} };

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

describe("EVIDENCE — style observables", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); });

  it("prints the real DOM for a spread of components", async () => {
    // Two that Tier 1 said APPLIED, several it said NOT-OBSERVED.
    for (const name of ["Container", "Card", "Button", "Badge", "Table", "Stack"]) {
      useEditorStore.getState().setInitial({
        pageSchemas: {
          home: {
            schemaVersion: "2", id: "home", route: "/",
            root: { id: "root", type: "Container", props: {}, children: [] },
          },
        },
        navFlow: NAV_FLOW as any, tokens: EMPTY_TOKENS,
      } as any);
      const store = useEditorStore.getState();
      const node = buildDroppedNode(name);
      store.dispatch({ type: "insertNode", pageId: "home", parentId: "root", index: 0, node } as any);
      for (const [k, v] of [["padding", "spacing.4"], ["radius", "radius.md"],
                            ["shadow", "shadow.md"], ["width", "321px"]] as Array<[string, string]>) {
        store.dispatch({ type: "updateStyle", pageId: "home", nodeId: node.id, styleKey: k, value: v } as any);
      }
      const page = (useEditorStore.getState().artifacts as any).pageSchemas.home;
      await act(async () => {
        root.render(
          <EngineProvider designSpec={{}} navFlow={NAV_FLOW as any} cssVarTokens={{}}>
            <Engine schema={page} previewData={{}} />
          </EngineProvider>,
        );
      });
      await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

      const el = container.querySelector(`[data-node-id="${node.id}"]`) as HTMLElement | null;
      const stored = JSON.stringify(page.root.children[0].style);
      console.log(`\n[EV] ${name}`);
      console.log(`[EV]   node.style in artifact : ${stored}`);
      console.log(`[EV]   element tag            : ${el ? el.tagName.toLowerCase() : "(node not in DOM)"}`);
      console.log(`[EV]   style attribute        : ${el?.getAttribute("style") ?? "(none)"}`);
      const inner = el?.firstElementChild as HTMLElement | null;
      console.log(`[EV]   first child            : ${inner ? inner.tagName.toLowerCase() + " style=" + (inner.getAttribute("style") ?? "(none)") : "(no child)"}`);
      const anyPad = el?.outerHTML.includes("spacing-4");
      console.log(`[EV]   'spacing-4' anywhere   : ${!!anyPad}`);
    }
    expect(true).toBe(true);
  }, 300_000);
});
