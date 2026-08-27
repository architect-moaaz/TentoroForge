/**
 * Editor hardening — regression locks for the audit fixes (store/undo layer).
 * Grows as more audit findings are fixed.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useEditorStore } from "@/lib/editor-store";

const TOKENS = { color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} };
const NAV = { version: "1.0", initialPage: "home", pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }], transitions: [], guards: {} };
function seed(children: any[] = []) {
  useEditorStore.getState().setInitial({
    pageSchemas: { home: { schemaVersion: "2", id: "home", route: "/", root: { id: "root", type: "Container", props: {}, children } } },
    navFlow: NAV as any, tokens: TOKENS,
  } as any);
}
const S = () => useEditorStore.getState();

describe("undo/redo dirty tracking (#8) — an undo/redo after autosave must re-persist", () => {
  beforeEach(() => seed([{ id: "btn", type: "Button", props: { label: "A" } }]));

  it("undo sets isDirty even after markClean simulated an autosave", () => {
    S().dispatch({ type: "updateProp", pageId: "home", nodeId: "btn", propName: "label", value: "B" });
    S().markClean(); // simulate the debounced autosave completing
    expect(S().isDirty).toBe(false);
    S().undo();
    expect(S().isDirty).toBe(true); // undo diverged in-memory from disk → must persist
    expect(S().artifacts!.pageSchemas.home.root.children[0].props.label).toBe("A");
  });

  it("redo also sets isDirty", () => {
    S().dispatch({ type: "updateProp", pageId: "home", nodeId: "btn", propName: "label", value: "B" });
    S().undo();
    S().markClean();
    S().redo();
    expect(S().isDirty).toBe(true);
    expect(S().artifacts!.pageSchemas.home.root.children[0].props.label).toBe("B");
  });

  it("markClean clears a prior saveError", () => {
    S().setSaveError("boom");
    expect(S().saveError).toBe("boom");
    S().markClean();
    expect(S().saveError).toBeNull();
  });
});

describe("dispatchBatch (#3, #31) — a multi-op gesture is ONE undo step", () => {
  beforeEach(() => seed([
    { id: "a", type: "Button", props: { label: "A" } },
    { id: "b", type: "Button", props: { label: "B" } },
    { id: "c", type: "Button", props: { label: "C" } },
  ]));

  it("batch-remove of 3 nodes reverts with a SINGLE undo", () => {
    S().dispatchBatch([
      { type: "removeNode", pageId: "home", nodeId: "a" },
      { type: "removeNode", pageId: "home", nodeId: "b" },
      { type: "removeNode", pageId: "home", nodeId: "c" },
    ]);
    expect(S().lastError).toBeNull();
    expect(S().artifacts!.pageSchemas.home.root.children.length).toBe(0);
    S().undo(); // ONE undo
    const ids = S().artifacts!.pageSchemas.home.root.children.map((c: any) => c.id);
    expect(ids).toEqual(["a", "b", "c"]);
    S().redo(); // ONE redo re-applies the whole batch
    expect(S().artifacts!.pageSchemas.home.root.children.length).toBe(0);
  });

  it("batch is all-or-nothing: a bad action commits nothing", () => {
    S().dispatchBatch([
      { type: "removeNode", pageId: "home", nodeId: "a" },
      { type: "removeNode", pageId: "home", nodeId: "does-not-exist" },
    ]);
    expect(S().lastError).toBeTruthy();
    // 'a' must NOT have been removed (transaction rolled back)
    expect(S().artifacts!.pageSchemas.home.root.children.map((c: any) => c.id)).toEqual(["a", "b", "c"]);
  });

  it("a corner-resize batch (width+height) is one undo", () => {
    S().dispatchBatch([
      { type: "updateStyle", pageId: "home", nodeId: "a", styleKey: "width", value: "200px" },
      { type: "updateStyle", pageId: "home", nodeId: "a", styleKey: "height", value: "100px" },
    ]);
    expect(S().artifacts!.pageSchemas.home.root.children[0].style).toEqual({ width: "200px", height: "100px" });
    S().undo(); // single undo clears BOTH
    expect(S().artifacts!.pageSchemas.home.root.children[0].style).toBeUndefined();
  });
});

describe("undo/redo crash-safety (#24) — a bad inverse must not throw uncaught", () => {
  beforeEach(() => seed([{ id: "btn", type: "Button", props: { label: "A" } }]));

  it("a corrupt undo entry surfaces lastError and drops the entry instead of throwing", () => {
    S().dispatch({ type: "updateProp", pageId: "home", nodeId: "btn", propName: "label", value: "B" });
    // Corrupt the top inverse so applyAction will throw (unknown node).
    const state = useEditorStore.getState();
    const bad = { ...(state.undoStack[state.undoStack.length - 1] as any), nodeId: "does-not-exist" };
    useEditorStore.setState({ undoStack: [...state.undoStack.slice(0, -1), bad as any] });
    expect(() => S().undo()).not.toThrow();
    expect(S().lastError).toBeTruthy();
    // the offending entry was dropped so a second press doesn't re-throw
    const depth = S().undoStack.length;
    expect(() => S().undo()).not.toThrow();
    expect(S().undoStack.length).toBeLessThanOrEqual(depth);
  });
});
