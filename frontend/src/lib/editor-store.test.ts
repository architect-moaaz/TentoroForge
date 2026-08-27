import { describe, it, expect, beforeEach } from "vitest";
import { useEditorStore } from "./editor-store";

function fixture() {
  return {
    pageSchemas: {
      home: {
        schemaVersion: "2" as const, id: "home", route: "/",
        root: { id: "n1", type: "Stack", children: [
          { id: "n2", type: "Text", props: { text: "Hello" } },
        ] },
      },
    },
    navFlow: {
      version: "1.0" as const, initialPage: "home",
      pages: [{ id: "home", route: "/", title: "Home",
                schemaFile: "src/schemas/home.json", params: [] }],
      transitions: [], guards: {},
    },
    tokens: {
      color: {}, typography: {}, spacing: {}, radius: {},
      shadow: {}, motion: {}, breakpoints: {},
    },
  };
}

beforeEach(() => {
  useEditorStore.setState({
    artifacts: null, undoStack: [], redoStack: [],
    selectedNodeId: null, selectedNodeIds: [], currentPageId: null,
  });
});

describe("editor-store", () => {
  it("setInitial seeds artifacts + currentPageId", () => {
    const f = fixture();
    useEditorStore.getState().setInitial(f);
    expect(useEditorStore.getState().artifacts).toEqual(f);
    expect(useEditorStore.getState().currentPageId).toBe("home");
  });

  it("dispatch updates artifacts + pushes inverse", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().dispatch({
      type: "updateProp", pageId: "home", nodeId: "n2",
      propName: "text", value: "World",
    });
    const state = useEditorStore.getState();
    expect((state.artifacts!.pageSchemas.home.root.children![0].props as any).text).toBe("World");
    expect(state.undoStack).toHaveLength(1);
    expect(state.redoStack).toHaveLength(0);
  });

  it("undo restores previous state and populates redoStack", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().dispatch({
      type: "updateProp", pageId: "home", nodeId: "n2",
      propName: "text", value: "World",
    });
    useEditorStore.getState().undo();
    const state = useEditorStore.getState();
    expect((state.artifacts!.pageSchemas.home.root.children![0].props as any).text).toBe("Hello");
    expect(state.undoStack).toHaveLength(0);
    expect(state.redoStack).toHaveLength(1);
  });

  it("redo replays an undone action", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().dispatch({
      type: "updateProp", pageId: "home", nodeId: "n2",
      propName: "text", value: "World",
    });
    useEditorStore.getState().undo();
    useEditorStore.getState().redo();
    expect((useEditorStore.getState().artifacts!.pageSchemas.home.root.children![0].props as any).text).toBe("World");
  });

  it("new dispatch clears redoStack", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().dispatch({
      type: "updateProp", pageId: "home", nodeId: "n2", propName: "text", value: "A",
    });
    useEditorStore.getState().undo();
    expect(useEditorStore.getState().redoStack).toHaveLength(1);
    useEditorStore.getState().dispatch({
      type: "updateProp", pageId: "home", nodeId: "n2", propName: "text", value: "B",
    });
    expect(useEditorStore.getState().redoStack).toHaveLength(0);
  });

  it("setSelection updates selectedNodeId", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().setSelection("n2");
    expect(useEditorStore.getState().selectedNodeId).toBe("n2");
    useEditorStore.getState().setSelection(null);
    expect(useEditorStore.getState().selectedNodeId).toBeNull();
  });

  it("setCurrentPage clears selection", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().setSelection("n2");
    useEditorStore.getState().setCurrentPage("home");
    expect(useEditorStore.getState().selectedNodeId).toBeNull();
  });

  it("setSelectionMulti sets array and derives selectedNodeId from first", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().setSelectionMulti(["n1", "n2"]);
    expect(useEditorStore.getState().selectedNodeIds).toEqual(["n1", "n2"]);
    expect(useEditorStore.getState().selectedNodeId).toBe("n1");
  });

  it("toggleSelection adds then removes", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().toggleSelection("n1");
    expect(useEditorStore.getState().selectedNodeIds).toEqual(["n1"]);
    useEditorStore.getState().toggleSelection("n2");
    expect(useEditorStore.getState().selectedNodeIds).toEqual(["n1", "n2"]);
    useEditorStore.getState().toggleSelection("n1");
    expect(useEditorStore.getState().selectedNodeIds).toEqual(["n2"]);
  });

  it("extendSelection appends without duplicates", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().extendSelection("n1");
    useEditorStore.getState().extendSelection("n1");
    expect(useEditorStore.getState().selectedNodeIds).toEqual(["n1"]);
  });

  it("clearSelection empties both fields", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().setSelectionMulti(["n1", "n2"]);
    useEditorStore.getState().clearSelection();
    expect(useEditorStore.getState().selectedNodeIds).toEqual([]);
    expect(useEditorStore.getState().selectedNodeId).toBeNull();
  });

  it("setSelection (singular) updates both fields", () => {
    useEditorStore.getState().setInitial(fixture());
    useEditorStore.getState().setSelection("n2");
    expect(useEditorStore.getState().selectedNodeId).toBe("n2");
    expect(useEditorStore.getState().selectedNodeIds).toEqual(["n2"]);
  });
});
