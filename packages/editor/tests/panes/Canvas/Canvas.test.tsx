import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { Canvas } from "../../../src/panes/Canvas/Canvas";
import { createEditorStore } from "../../../src/state/store";

const emptyRegistry = { has: () => false, get: () => undefined } as any;

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  root: { id: "r", type: "Box", children: [
    { id: "child", type: "Text", props: { content: "hello" } },
  ]},
});

describe("Canvas", () => {
  it("renders the SchemaRenderer output", () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    const { container } = render(<Canvas store={store} registry={emptyRegistry} />);
    expect(container.textContent).toContain("hello");
  });

  it("clicking a rendered node selects it", () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    const { container } = render(<Canvas store={store} registry={emptyRegistry} />);
    const childEl = container.querySelector('[data-node-id="child"]')!;
    fireEvent.click(childEl);
    expect(store.getState().pages["x"].selection).toEqual(["child"]);
  });
});

// ---------------------------------------------------------------------------
// Task 33: Custom node dispatch via ctx.customRenderer
// Canvas should render Custom nodes via CustomNodePreview (identified by
// data-custom-preview) instead of the renderer's default dangerouslySetInnerHTML.
// ---------------------------------------------------------------------------

describe("Canvas — Custom node dispatch", () => {
  // 1. Stack root containing a Custom child → CustomNodePreview is mounted
  it("renders a Custom node inside a Stack via CustomNodePreview", () => {
    const store = createEditorStore();
    store.getState().openPage("x", {
      schemaVersion: "1", id: "p", route: "/",
      root: {
        id: "r", type: "Stack", children: [
          { id: "cust", type: "Custom", props: { html: "<p>hi</p>" } },
        ],
      },
    });
    const { container } = render(<Canvas store={store} registry={emptyRegistry} />);
    // CustomNodePreview marks its wrapper with data-custom-preview
    expect(container.querySelector("[data-custom-preview]")).not.toBeNull();
  });

  // 2. Root IS a Custom node → CustomNodePreview is mounted
  it("renders a root Custom node via CustomNodePreview", () => {
    const store = createEditorStore();
    store.getState().openPage("x", {
      schemaVersion: "1", id: "p", route: "/",
      root: { id: "cust-root", type: "Custom", props: { html: "" } },
    });
    const { container } = render(<Canvas store={store} registry={emptyRegistry} />);
    expect(container.querySelector("[data-custom-preview]")).not.toBeNull();
    expect(container.querySelector("[data-node-id='cust-root']")).not.toBeNull();
  });

  // 3. Schema with no Custom nodes → no data-custom-preview markers in DOM
  it("does not add data-custom-preview when no Custom nodes exist", () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    const { container } = render(<Canvas store={store} registry={emptyRegistry} />);
    expect(container.querySelector("[data-custom-preview]")).toBeNull();
  });
});
