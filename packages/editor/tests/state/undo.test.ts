import { describe, it, expect, beforeEach } from "vitest";
import { createEditorStore } from "../../src/state/store";
import { buildInsertNode, buildSetProp } from "../../src/state/mutations";

const page = () => ({
  schemaVersion: "1" as const, id: "p", route: "/",
  root: { id: "r", type: "Stack", children: [
    { id: "a", type: "Text", props: { content: "A" } },
  ]},
});

const PATH = "x";

let store: ReturnType<typeof createEditorStore>;
beforeEach(() => {
  store = createEditorStore();
  store.getState().openPage(PATH, page() as any);
});

describe("store mutations", () => {
  it("apply increments schemaVersion + sets dirty", () => {
    const v0 = store.getState().pages[PATH].schemaVersion;
    store.getState().apply(buildSetProp("a", "content", "X", page() as any));
    expect(store.getState().pages[PATH].schemaVersion).toBe(v0 + 1);
    expect(store.getState().pages[PATH].saveState).toBe("dirty");
  });

  it("undo reverses the last mutation", () => {
    const m = buildSetProp("a", "content", "X", page() as any);
    store.getState().apply(m);
    expect((store.getState().pages[PATH].schema.root as any).children[0].props.content).toBe("X");
    store.getState().undo();
    expect((store.getState().pages[PATH].schema.root as any).children[0].props.content).toBe("A");
  });

  it("redo re-applies an undone mutation", () => {
    const m = buildSetProp("a", "content", "X", page() as any);
    store.getState().apply(m);
    store.getState().undo();
    store.getState().redo();
    expect((store.getState().pages[PATH].schema.root as any).children[0].props.content).toBe("X");
  });

  it("history limit drops oldest", () => {
    for (let i = 0; i < 105; i++) {
      store.getState().apply(buildSetProp("a", "content", `v${i}`, store.getState().pages[PATH].schema));
    }
    expect(store.getState().pages[PATH].history.length).toBe(100);
  });

  it("save lifecycle marks clean after markSaved", () => {
    store.getState().apply(buildSetProp("a", "content", "X", page() as any));
    expect(store.getState().pages[PATH].saveState).toBe("dirty");
    store.getState().markSaved(store.getState().pages[PATH].schema);
    expect(store.getState().pages[PATH].saveState).toBe("saved");
  });

  it("dirty re-emerges if user mutates after save", () => {
    store.getState().markSaved(store.getState().pages[PATH].schema);
    store.getState().apply(buildSetProp("a", "content", "X", store.getState().pages[PATH].schema));
    expect(store.getState().pages[PATH].saveState).toBe("dirty");
  });
});
