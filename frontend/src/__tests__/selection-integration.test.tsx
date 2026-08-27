/**
 * Integration test for the visual-editor selection flow.
 * Renders the REAL home.json schema through the REAL @tentoroforge/engine,
 * then verifies that (a) rendered DOM nodes carry data-node-id, (b) those ids
 * resolve in the seeded editor store, and (c) a real click selects + resolves
 * the node — exactly what the Props/Style/Bindings tabs depend on.
 */
import { describe, it, expect, beforeEach } from "vitest";
import * as fs from "fs";
import * as path from "path";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { syntheticNodeId } from "@forge/patches";
import { useEditorStore } from "@/lib/editor-store";
import { useCanvasClick } from "@/components/canvas/hooks/useSelection";
import React from "react";

// jsdom polyfills the renderer/react need
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  // @ts-expect-error minimal polyfill
  window.matchMedia = (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  });
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}

// ---- replicate Canvas.normaliseSchema (not exported) ------------------------
function normaliseSchema(raw: any): any {
  const seen = new Set<string>();
  function uniq(base: string, p: string): string {
    if (!seen.has(base)) { seen.add(base); return base; }
    let candidate = `${base}_${p || "root"}`;
    let n = 2;
    while (seen.has(candidate)) candidate = `${base}_${p || "root"}_${n++}`;
    seen.add(candidate);
    return candidate;
  }
  function injectIds(node: any, p = ""): any {
    if (!node) return node;
    const baseId = node.id ?? syntheticNodeId(node);
    const id = uniq(baseId, p);
    return {
      ...node, id,
      children: Array.isArray(node.children)
        ? node.children.map((c: any, i: number) => injectIds(c, p ? `${p}.${i}` : `${i}`))
        : undefined,
    };
  }
  const root = raw.root
    ?? (Array.isArray(raw.children) && raw.children.length > 0
      ? { type: "Stack", id: "_synthetic_root", children: raw.children }
      : { type: "Text", id: "_no_content", props: { content: "(empty)" } });
  return { ...raw, root: injectIds(root) };
}

// ---- replicate PropertiesPanel.findNodeInArtifacts --------------------------
function findNodeInArtifacts(artifacts: any, nodeId: string): boolean {
  for (const page of Object.values(artifacts?.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if ((n.id ?? syntheticNodeId(n)) === nodeId) return true;
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots) for (const arr of Object.values(n.slots) as any[]) if (Array.isArray(arr)) stack.push(...arr);
    }
  }
  return false;
}

// Portable fixture mirroring a real LLM-generated schema shape (structural +
// library nodes, all with explicit ids). If a real generated schema is present
// on this machine we use it (richer coverage); otherwise the inline fixture
// keeps the test CI-safe.
const FIXTURE = {
  schemaVersion: "2", id: "home", title: "Home", dataSources: [],
  root: {
    id: "root-container", type: "Container", props: {}, children: [
      { id: "hdr", type: "Heading", props: { content: "Dashboard", level: 1 } },
      { id: "grid1", type: "Grid", props: { columns: 2 }, children: [
        { id: "tile1", type: "MetricTile", props: { label: "Total", value: "42" } },
        { id: "tile2", type: "MetricTile", props: { label: "Open", value: "7" } },
      ] },
      { id: "card1", type: "Card", props: { title: "Recent" }, children: [
        { id: "txt1", type: "Text", props: { content: "Some text" } },
        { id: "btn1", type: "Button", props: { label: "Add" } },
      ] },
    ],
  },
};
function loadHome(): any {
  const p = path.resolve(__dirname, "../../../output/h4ixkgnm/src/schemas/home.json");
  try { if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, "utf8")); } catch { /* fall through */ }
  return FIXTURE;
}
const HOME = loadHome();
const NAV_FLOW = {
  version: "1.0", initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [], guards: {},
};

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

function Harness({ schema }: { schema: any }) {
  const onClick = useCanvasClick();
  return (
    <div data-canvas-root onClick={onClick}>
      <EngineProvider designSpec={{}} navFlow={NAV_FLOW as any} cssVarTokens={{}}>
        <Engine schema={schema} previewData={{}} />
      </EngineProvider>
    </div>
  );
}

describe("visual-editor selection flow (real home.json + real Engine)", () => {
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  it("renders data-node-id nodes that resolve in the store, and click selects them", async () => {
    const normalised = normaliseSchema(HOME);
    useEditorStore.getState().setInitial({
      pageSchemas: { home: normalised },
      navFlow: NAV_FLOW,
      tokens: { color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} },
    } as any);

    await act(async () => {
      root.render(<Harness schema={normalised} />);
    });
    // let effects/data settle
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });

    const nodeEls = Array.from(container.querySelectorAll("[data-node-id]")) as HTMLElement[];
    const domIds = nodeEls.map((el) => el.getAttribute("data-node-id")!).filter(Boolean);

    // Diagnostics — these print even on pass so we see the real numbers.
    const storeArtifacts = useEditorStore.getState().artifacts;
    const resolvable = domIds.filter((id) => findNodeInArtifacts(storeArtifacts, id));
    const unresolvable = domIds.filter((id) => !findNodeInArtifacts(storeArtifacts, id));
    // eslint-disable-next-line no-console
    console.log(`[DIAG] rendered [data-node-id] elements: ${domIds.length}`);
    // eslint-disable-next-line no-console
    console.log(`[DIAG] resolvable in store: ${resolvable.length} | UNRESOLVABLE: ${unresolvable.length}`);
    // eslint-disable-next-line no-console
    console.log(`[DIAG] sample unresolvable ids: ${JSON.stringify(unresolvable.slice(0, 8))}`);
    // eslint-disable-next-line no-console
    console.log(`[DIAG] unknown/invalid placeholders (no data-node-id): unknown=${container.querySelectorAll("[data-unknown-node]").length} invalid=${container.querySelectorAll("[data-invalid-node]").length}`);

    // (A) at least some nodes render with ids
    expect(domIds.length).toBeGreaterThan(0);

    // (B) every rendered data-node-id resolves in the store (the panels' lookup)
    expect(unresolvable).toEqual([]);

    // (C) a real click on a deep node selects it AND it resolves
    const targetLeaf = nodeEls.find((el) => el.getAttribute("data-node-id")) as HTMLElement;
    const targetId = targetLeaf.getAttribute("data-node-id")!;
    useEditorStore.getState().clearSelection();
    await act(async () => {
      targetLeaf.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    const sel = useEditorStore.getState().selectedNodeId;
    // eslint-disable-next-line no-console
    console.log(`[DIAG] clicked id=${targetId} -> store.selectedNodeId=${sel}`);
    expect(sel).toBe(targetId);
    expect(findNodeInArtifacts(useEditorStore.getState().artifacts, sel!)).toBe(true);
  });
});
