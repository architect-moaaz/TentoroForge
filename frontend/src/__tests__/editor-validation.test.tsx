/**
 * VISUAL EDITOR — full validation suite.
 *
 * Proves the previously-fixed editor work still holds after the smith merge,
 * end-to-end against the REAL code paths (no drifting copies):
 *   • Palette covers every registry component (nothing undroppable).
 *   • Every one of the 106 components drops → commits (validateForCommit) →
 *     renders with a selectable data-node-id (not a ⚠ orphan / unknown type).
 *   • Reorder (moveNode), duplicate (Cmd+D), delete (removeNode) behave.
 *   • All four inspector tabs write the right action and undo restores it:
 *       Props→updateProp, Style→updateStyle, Bindings→bindProp, Tokens→updateToken.
 *
 * It imports the actual helpers from useDrop (validateDrop / buildDroppedNode)
 * and dispatches through the actual editor-store, so a regression in the real
 * code fails here — not a paraphrase of it.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import React from "react";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { starterRegistry } from "@forge/registry";
import {
  validateDrop,
  buildDroppedNode,
} from "@/components/canvas/hooks/useDrop";
import { useEditorStore } from "@/lib/editor-store";

// ---- jsdom polyfills the renderer/react need --------------------------------
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

// The palette renders categories in this fixed order; a registry entry whose
// category isn't here would silently never appear (undroppable). Mirrors
// frontend/src/components/palette/Palette.tsx CATEGORY_ORDER.
const PALETTE_CATEGORY_ORDER = [
  "layout", "input", "display", "interactive", "data", "feedback", "navigation",
];

const NAV_FLOW = {
  version: "1.0", initialPage: "home",
  pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
  transitions: [], guards: {},
};

const ALL_ENTRIES = Object.values(starterRegistry) as Array<{
  name: string; category: string; slots: { type: string; accepts?: string[] };
}>;

const EMPTY_TOKENS = {
  color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {},
};

function makePage(children: any[] = []) {
  return {
    schemaVersion: "2", id: "home", route: "/",
    root: { id: "root", type: "Container", props: {}, children },
  };
}
function seed(page: any, tokens: any = EMPTY_TOKENS) {
  useEditorStore.getState().setInitial({
    pageSchemas: { home: page },
    navFlow: NAV_FLOW as any,
    tokens,
  } as any);
}
function currentHome() {
  return (useEditorStore.getState().artifacts as any).pageSchemas.home;
}

// ---- render harness ---------------------------------------------------------
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
function mount() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
}
function unmount() {
  act(() => root.unmount());
  container.remove();
}
async function renderPage(page: any) {
  await act(async () => {
    root.render(
      <EngineProvider designSpec={{}} navFlow={NAV_FLOW as any} cssVarTokens={{}}>
        <Engine schema={page} previewData={{}} />
      </EngineProvider>,
    );
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
}

// =============================================================================
describe("palette coverage — every component is reachable", () => {
  it("exposes exactly 106 components across the 6 real categories", () => {
    expect(ALL_ENTRIES.length).toBe(106);
    const byCat = ALL_ENTRIES.reduce<Record<string, number>>((m, e) => {
      m[e.category] = (m[e.category] ?? 0) + 1; return m;
    }, {});
    expect(byCat).toEqual({ layout: 18, input: 30, display: 29, data: 11, feedback: 11, navigation: 7 });
  });

  it("no component has a category the palette can't render (undroppable)", () => {
    const orphaned = ALL_ENTRIES.filter((e) => !PALETTE_CATEGORY_ORDER.includes(e.category));
    expect(orphaned.map((e) => e.name)).toEqual([]);
  });

  it("wildcard container (Dialog) accepts any child type", () => {
    // Regression: `["*"].includes("Button")` was false, so nothing could be
    // dropped/reordered into a Dialog. The wildcard must be honored.
    expect(validateDrop("Dialog", "Button").ok).toBe(true);
    expect(validateDrop("Dialog", "Table").ok).toBe(true);
    // A true leaf still rejects children.
    expect(validateDrop("Badge", "Button").ok).toBe(false);
  });
});

// =============================================================================
describe("drop → commit — every component adds cleanly via insertNode", () => {
  it("all 106 build a node, pass validateDrop into a Container, and commit (no validateForCommit reject)", () => {
    seed(makePage([]));
    const store = useEditorStore.getState();
    const failures: string[] = [];
    for (const entry of ALL_ENTRIES) {
      const drop = validateDrop("Container", entry.name);
      if (!drop.ok) { failures.push(`${entry.name}: validateDrop → ${drop.reason}`); continue; }
      const node = buildDroppedNode(entry.name);
      const before = currentHome().root.children.length;
      store.dispatch({ type: "insertNode", pageId: "home", parentId: "root", index: before, node });
      const err = useEditorStore.getState().lastError;
      const after = currentHome().root.children.length;
      if (err) failures.push(`${entry.name}: commit rejected → ${err}`);
      else if (after !== before + 1) failures.push(`${entry.name}: not inserted (len ${before}→${after})`);
    }
    if (failures.length) console.error(`[COMMIT FAILURES ${failures.length}]\n` + failures.join("\n"));
    expect(failures).toEqual([]);
  });
});

// =============================================================================
describe("drop → render — every component renders selectably", () => {
  beforeEach(mount);
  afterEach(unmount);

  it("every dropped component renders with a data-node-id (no ⚠ orphan, no unknown type)", async () => {
    seed(makePage([]));
    const store = useEditorStore.getState();
    const inserted: Array<{ name: string; id: string }> = [];
    for (const entry of ALL_ENTRIES) {
      if (!validateDrop("Container", entry.name).ok) continue;
      const node = buildDroppedNode(entry.name);
      const idx = currentHome().root.children.length;
      store.dispatch({ type: "insertNode", pageId: "home", parentId: "root", index: idx, node });
      inserted.push({ name: entry.name, id: node.id });
    }

    await renderPage(currentHome());

    const selectable: string[] = [];
    const invalidProps: string[] = [];
    const unknownType: string[] = [];
    const notRendered: string[] = [];
    for (const { name, id } of inserted) {
      if (container.querySelector(`[data-node-id="${id}"]`)) selectable.push(name);
      else if (container.querySelector(`[data-invalid-node="${name}"]`)) invalidProps.push(name);
      else if (container.querySelector(`[data-unknown-node="${name}"]`)) unknownType.push(name);
      else notRendered.push(name);
    }

    console.log(
      `[RENDER REPORT] selectable=${selectable.length} invalidProps=${invalidProps.length} ` +
      `unknownType=${unknownType.length} notRendered=${notRendered.length}`);
    if (invalidProps.length) console.log(`[invalid-props] ${invalidProps.join(", ")}`);
    if (unknownType.length) console.log(`[unknown-type] ${unknownType.join(", ")}`);
    if (notRendered.length) console.log(`[not-rendered] ${notRendered.join(", ")}`);

    // Hard requirement: no component may be unknown to the renderer's library —
    // that would mean the palette lists something that can't render at all.
    expect(unknownType).toEqual([]);
    // Every component's registry default props must satisfy the renderer's Zod
    // schema (no "⚠ invalid props" placeholder on a fresh drop).
    expect(invalidProps).toEqual([]);
    // The ONLY components that don't paint on an empty canvas are the data/logic
    // control-flow builtins — they correctly render nothing until bound to data.
    // Anything else blank is a real regression.
    const CONFIG_DRIVEN = new Set(["Repeat", "Conditional", "DataBoundary", "Slot"]);
    const unexpectedBlank = notRendered.filter((n) => !CONFIG_DRIVEN.has(n));
    expect(unexpectedBlank).toEqual([]);
    // 106 total − 4 config-driven = 102 must be directly selectable on drop.
    expect(selectable.length).toBeGreaterThanOrEqual(102);
  });
});

// =============================================================================
describe("reorder — moveNode relocates a node between containers", () => {
  it("moves a leaf from one container into another and restores on undo", () => {
    seed(makePage([
      { id: "boxA", type: "Container", props: {}, children: [{ id: "leaf1", type: "Text", props: { content: "x" } }] },
      { id: "boxB", type: "Container", props: {}, children: [] },
    ]));
    const store = useEditorStore.getState();
    store.dispatch({ type: "moveNode", pageId: "home", nodeId: "leaf1", newParentId: "boxB", newIndex: 0 });
    expect(useEditorStore.getState().lastError).toBeNull();
    let home = currentHome();
    expect(home.root.children.find((c: any) => c.id === "boxA").children.length).toBe(0);
    expect(home.root.children.find((c: any) => c.id === "boxB").children.map((c: any) => c.id)).toEqual(["leaf1"]);
    useEditorStore.getState().undo();
    home = currentHome();
    expect(home.root.children.find((c: any) => c.id === "boxA").children.map((c: any) => c.id)).toEqual(["leaf1"]);
    expect(home.root.children.find((c: any) => c.id === "boxB").children.length).toBe(0);
  });
});

// =============================================================================
describe("duplicate — Cmd+D must work for leaves AND containers", () => {
  it("duplicates a leaf", () => {
    seed(makePage([{ id: "btn", type: "Button", props: { label: "A" } }]));
    useEditorStore.getState().dispatch({ type: "duplicateNode", pageId: "home", nodeId: "btn" });
    expect(useEditorStore.getState().lastError).toBeNull();
    expect(currentHome().root.children.length).toBe(2);
  });

  it("duplicates a CONTAINER with children (must re-id the whole subtree)", () => {
    seed(makePage([
      { id: "card", type: "Card", props: { title: "T" }, children: [
        { id: "t1", type: "Text", props: { content: "x" } },
        { id: "b1", type: "Button", props: { label: "y" } },
      ] },
    ]));
    useEditorStore.getState().dispatch({ type: "duplicateNode", pageId: "home", nodeId: "card" });
    const err = useEditorStore.getState().lastError;
    expect(err).toBeNull(); // currently FAILS: dup child ids trip validateForCommit
    expect(currentHome().root.children.length).toBe(2);
    // the copied subtree must have DISTINCT ids from the original
    const ids: string[] = [];
    const walk = (n: any) => { ids.push(n.id); (n.children ?? []).forEach(walk); };
    currentHome().root.children.forEach(walk);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// =============================================================================
describe("delete — removeNode never crashes the dispatch", () => {
  it("removes a child and restores on undo", () => {
    seed(makePage([{ id: "btn", type: "Button", props: { label: "A" } }]));
    useEditorStore.getState().dispatch({ type: "removeNode", pageId: "home", nodeId: "btn" });
    expect(useEditorStore.getState().lastError).toBeNull();
    expect(currentHome().root.children.length).toBe(0);
    useEditorStore.getState().undo();
    expect(currentHome().root.children.map((c: any) => c.id)).toEqual(["btn"]);
  });

  it("deleting the ROOT is rejected gracefully (no uncaught throw)", () => {
    seed(makePage([{ id: "btn", type: "Button", props: { label: "A" } }]));
    // Selecting + deleting the root must not throw an uncaught error out of dispatch.
    expect(() =>
      useEditorStore.getState().dispatch({ type: "removeNode", pageId: "home", nodeId: "root" }),
    ).not.toThrow();
    // root is still there
    expect(currentHome().root.id).toBe("root");
  });
});

// =============================================================================
describe("inspector tabs — each writes the right action and undo restores", () => {
  beforeEach(() => {
    seed(makePage([{ id: "btn", type: "Button", props: { label: "Old" } }]),
      { color: { primary: { "500": "#000000" } }, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} });
  });

  it("PROPS tab: updateProp changes node.props and undo restores", () => {
    useEditorStore.getState().dispatch({ type: "updateProp", pageId: "home", nodeId: "btn", propName: "label", value: "New" });
    expect(currentHome().root.children[0].props.label).toBe("New");
    useEditorStore.getState().undo();
    expect(currentHome().root.children[0].props.label).toBe("Old");
  });

  it("STYLE tab: updateStyle writes node.style envelope and undo restores", () => {
    useEditorStore.getState().dispatch({ type: "updateStyle", pageId: "home", nodeId: "btn", styleKey: "padding", value: "spacing.4" });
    expect(currentHome().root.children[0].style).toEqual({ padding: "spacing.4" });
    useEditorStore.getState().undo();
    expect(currentHome().root.children[0].style).toBeUndefined();
  });

  it("BINDINGS tab: bindProp wraps the prop in {$binding} and undo restores the literal", () => {
    useEditorStore.getState().dispatch({ type: "bindProp", pageId: "home", nodeId: "btn", propName: "label", binding: "user.name" });
    expect(currentHome().root.children[0].props.label).toEqual({ $binding: "user.name" });
    useEditorStore.getState().undo();
    expect(currentHome().root.children[0].props.label).toBe("Old");
  });

  it("TOKENS tab: updateToken changes the global token and undo restores", () => {
    useEditorStore.getState().dispatch({ type: "updateToken", path: ["color", "primary", "500"], value: "#123456" });
    expect((currentHome(), (useEditorStore.getState().artifacts as any).tokens.color.primary["500"])).toBe("#123456");
    useEditorStore.getState().undo();
    expect((useEditorStore.getState().artifacts as any).tokens.color.primary["500"]).toBe("#000000");
  });
});

// =============================================================================
describe("component sizing (Phase B) — width/height render RAW across node kinds", () => {
  beforeEach(mount);
  afterEach(unmount);

  it("updateStyle writes every size key to node.style and undo restores", () => {
    seed(makePage([{ id: "card", type: "Card", props: { title: "T" }, children: [] }]));
    const store = useEditorStore.getState();
    store.dispatch({ type: "updateStyle", pageId: "home", nodeId: "card", styleKey: "width", value: "240px" });
    store.dispatch({ type: "updateStyle", pageId: "home", nodeId: "card", styleKey: "minHeight", value: "120px" });
    expect(currentHome().root.children[0].style).toEqual({ width: "240px", minHeight: "120px" });
    // clearing a size key (value "") removes it
    store.dispatch({ type: "updateStyle", pageId: "home", nodeId: "card", styleKey: "width", value: "" });
    expect(currentHome().root.children[0].style).toEqual({ minHeight: "120px" });
    useEditorStore.getState().undo(); // restore width
    expect(currentHome().root.children[0].style).toEqual({ width: "240px", minHeight: "120px" });
  });

  it("renders RAW width/height/maxWidth on a STRUCTURAL node (not var(--token-…))", async () => {
    seed(makePage([{
      id: "sbox", type: "Stack",
      props: { direction: "vertical" },
      style: { width: "240px", height: "120px", maxWidth: "50%" },
      children: [{ id: "t", type: "Text", props: { content: "x" } }],
    }]));
    await renderPage(currentHome());
    const el = container.querySelector('[data-node-id="sbox"]') as HTMLElement;
    expect(el).toBeTruthy();
    expect(el.style.width).toBe("240px");
    expect(el.style.height).toBe("120px");
    expect(el.style.maxWidth).toBe("50%");
    // must NOT be token-wrapped
    expect(el.style.width.includes("var(")).toBe(false);
  });

  it("renders RAW width on a LIBRARY node (Card) too", async () => {
    seed(makePage([{
      id: "card2", type: "Card",
      props: { title: "T" },
      style: { width: "300px", minHeight: "80px" },
      children: [{ id: "tx", type: "Text", props: { content: "hi" } }],
    }]));
    await renderPage(currentHome());
    const wrapper = container.querySelector('[data-node-id="card2"]') as HTMLElement;
    expect(wrapper).toBeTruthy();
    // data-node-id sits on a display:contents span; the sized box is it or a descendant.
    const candidates = [wrapper, ...Array.from(wrapper.querySelectorAll<HTMLElement>("*"))];
    const sized = candidates.some((n) => n.style?.width === "300px");
    expect(sized).toBe(true);
  });
});
