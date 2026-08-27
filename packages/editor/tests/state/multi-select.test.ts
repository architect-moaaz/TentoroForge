import { describe, it, expect, beforeEach } from "vitest";
import { createEditorStore } from "../../src/state/store";

const page = (): any => ({ schemaVersion: "1", id: "p", route: "/", root: { id: "r", type: "Stack", children: [
  { id: "a", type: "Text", props: { content: "A" } },
  { id: "b", type: "Text", props: { content: "B" } },
  { id: "c", type: "Text", props: { content: "C" } },
]}});

let store: ReturnType<typeof createEditorStore>;
beforeEach(() => { store = createEditorStore(); store.getState().openPage("p", page()); });

describe("multi-select selection helpers", () => {
  it("selectNode replaces selection with [id]", () => {
    store.getState().selectNode("a");
    store.getState().selectNode("b");
    expect(store.getState().pages.p.selection).toEqual(["b"]);
  });
  it("toggleSelection adds when absent, removes when present", () => {
    store.getState().selectNode("a");
    store.getState().toggleSelection("b");
    expect(store.getState().pages.p.selection).toEqual(["a", "b"]);
    store.getState().toggleSelection("a");
    expect(store.getState().pages.p.selection).toEqual(["b"]);
  });
});
