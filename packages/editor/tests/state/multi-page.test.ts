import { describe, it, expect, beforeEach } from "vitest";
import { createEditorStore } from "../../src/state/store";
import { buildSetProp } from "../../src/state/mutations";

const pageA = (): any => ({ schemaVersion: "1", id: "pA", route: "/a", root: { id: "rA", type: "Text", props: { content: "A" } } });
const pageB = (): any => ({ schemaVersion: "1", id: "pB", route: "/b", root: { id: "rB", type: "Text", props: { content: "B" } } });

let store: ReturnType<typeof createEditorStore>;
beforeEach(() => {
  store = createEditorStore();
});

describe("multi-page store", () => {
  it("opens a page and sets currentPath", () => {
    store.getState().openPage("a/list", pageA());
    expect(store.getState().currentPath).toBe("a/list");
    expect(Object.keys(store.getState().pages)).toEqual(["a/list"]);
  });

  it("switching pages preserves edit state on each", () => {
    store.getState().openPage("a/list", pageA());
    store.getState().apply(buildSetProp("rA", "content", "AA", store.getState().pages["a/list"].schema));
    expect(store.getState().pages["a/list"].saveState).toBe("dirty");

    store.getState().openPage("b/list", pageB());
    expect(store.getState().currentPath).toBe("b/list");
    expect(store.getState().pages["b/list"].saveState).toBe("clean");

    store.getState().switchPage("a/list");
    expect(store.getState().pages["a/list"].schema.root.props.content).toBe("AA");
    expect(store.getState().pages["a/list"].saveState).toBe("dirty");
  });

  it("apply targets the current page only", () => {
    store.getState().openPage("a/list", pageA());
    store.getState().openPage("b/list", pageB());
    expect(store.getState().currentPath).toBe("b/list");
    store.getState().apply(buildSetProp("rB", "content", "BB", store.getState().pages["b/list"].schema));
    expect(store.getState().pages["b/list"].schema.root.props.content).toBe("BB");
    expect(store.getState().pages["a/list"].schema.root.props.content).toBe("A");
  });

  it("undo only affects current page", () => {
    store.getState().openPage("a/list", pageA());
    store.getState().apply(buildSetProp("rA", "content", "AA", store.getState().pages["a/list"].schema));
    store.getState().openPage("b/list", pageB());
    store.getState().apply(buildSetProp("rB", "content", "BB", store.getState().pages["b/list"].schema));
    store.getState().undo();
    expect(store.getState().pages["b/list"].schema.root.props.content).toBe("B");
    expect(store.getState().pages["a/list"].schema.root.props.content).toBe("AA");
  });

  it("closePage drops the page from state", () => {
    store.getState().openPage("a/list", pageA());
    store.getState().openPage("b/list", pageB());
    store.getState().closePage("a/list");
    expect(Object.keys(store.getState().pages)).toEqual(["b/list"]);
    expect(store.getState().currentPath).toBe("b/list");
  });

  it("closing the current page falls back to most recently opened other page", () => {
    store.getState().openPage("a/list", pageA());
    store.getState().openPage("b/list", pageB());
    store.getState().closePage("b/list");
    expect(store.getState().currentPath).toBe("a/list");
  });

  it("closing the only page sets currentPath to null", () => {
    store.getState().openPage("a/list", pageA());
    store.getState().closePage("a/list");
    expect(store.getState().currentPath).toBeNull();
    expect(Object.keys(store.getState().pages)).toEqual([]);
  });
});
