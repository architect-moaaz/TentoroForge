import { describe, it, expect, beforeEach } from "vitest";
import { createEditorStore } from "../../src/state/store";

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  root: { id: "r", type: "Stack", children: [
    { id: "a", type: "Text", props: { content: "A" } },
    { id: "b", type: "Text", props: { content: "B" } },
  ]},
});

let store: ReturnType<typeof createEditorStore>;
beforeEach(() => { store = createEditorStore(); });

describe("clipboard", () => {
  it("copy captures selected subtrees", () => {
    store.getState().openPage("x", page());
    store.getState().selectNode("a");
    store.getState().toggleSelection("b");
    store.getState().copyToClipboard();
    expect(store.getState().clipboard?.nodes.map((n: any) => n.id)).toEqual(["a", "b"]);
  });

  it("paste creates new IDs and inserts into root when no selection", () => {
    store.getState().openPage("x", page());
    store.getState().selectNode("a");
    store.getState().copyToClipboard();
    store.getState().clearSelection();
    store.getState().pasteFromClipboard();
    const children = store.getState().pages.x.schema.root.children;
    // Original 2 + 1 paste = 3
    expect(children.length).toBe(3);
    // Pasted node has different id
    expect(children[2].id).not.toBe("a");
    expect(children[2].props.content).toBe("A");
  });

  it("cut removes the selection and stores in clipboard", () => {
    store.getState().openPage("x", page());
    store.getState().selectNode("a");
    store.getState().cutToClipboard();
    expect(store.getState().pages.x.schema.root.children.length).toBe(1);
    expect(store.getState().clipboard?.mode).toBe("cut");
    expect(store.getState().clipboard?.nodes[0].id).toBe("a");
  });

  it("paste across pages works", () => {
    store.getState().openPage("x", page());
    store.getState().selectNode("a");
    store.getState().copyToClipboard();
    store.getState().openPage("y", { ...page(), id: "py" });
    expect(store.getState().currentPath).toBe("y");
    store.getState().pasteFromClipboard();
    const children = store.getState().pages.y.schema.root.children;
    expect(children.length).toBe(3);  // 2 original + 1 pasted
  });
});
