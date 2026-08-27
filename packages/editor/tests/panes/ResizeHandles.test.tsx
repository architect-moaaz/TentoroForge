import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { ResizeHandles } from "../../src/panes/Canvas/ResizeHandles";
import { createEditorStore } from "../../src/state/store";

// Minimal page schema
const page = (): any => ({
  schemaVersion: "1",
  id: "p",
  route: "/",
  root: { id: "root", type: "Box", children: [
    { id: "child-a", type: "Box", children: [] },
    { id: "child-b", type: "Box", children: [] },
  ] },
});

const theme: any = {
  spacing: {
    "spacing.0":  "0px",
    "spacing.4":  "1rem",   // 16px
    "spacing.8":  "2rem",   // 32px
    "spacing.16": "4rem",   // 64px
    "spacing.32": "8rem",   // 128px
    "spacing.64": "16rem",  // 256px
  },
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ResizeHandles", () => {
  it("renders 8 handles when exactly one node is selected", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("root");
    store.getState().loadTheme(theme, "default");

    const { container } = render(
      <ResizeHandles store={store} rect={{ width: 100, height: 50 }} />
    );

    const handles = container.querySelectorAll("[data-resize-handle]");
    expect(handles).toHaveLength(8);
  });

  it("renders nothing when no node is selected", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    // Leave selection empty (clearSelection keeps it empty)
    store.getState().clearSelection();

    const { container } = render(
      <ResizeHandles store={store} rect={{ width: 100, height: 50 }} />
    );

    expect(container.querySelectorAll("[data-resize-handle]")).toHaveLength(0);
  });

  it("renders nothing when multiple nodes are selected", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    // Select two nodes
    store.getState().selectNode("child-a");
    store.getState().toggleSelection("child-b");

    const { container } = render(
      <ResizeHandles store={store} rect={{ width: 100, height: 50 }} />
    );

    expect(container.querySelectorAll("[data-resize-handle]")).toHaveLength(0);
  });

  it("mousedown on a handle starts the drag (does not throw)", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("root");
    store.getState().loadTheme(theme, "default");

    const { container } = render(
      <ResizeHandles store={store} rect={{ width: 100, height: 50 }} />
    );

    const seHandle = container.querySelector('[data-resize-handle="se"]')!;
    expect(seHandle).not.toBeNull();

    // mousedown should not throw
    expect(() =>
      fireEvent.mouseDown(seHandle, { clientX: 10, clientY: 10, bubbles: true })
    ).not.toThrow();
  });

  it("mouseup after drag dispatches a setStyle mutation with token-snapped value", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("root");
    store.getState().loadTheme(theme, "default");

    const applySpy = vi.spyOn(store.getState(), "apply");

    const { container } = render(
      <ResizeHandles store={store} rect={{ width: 100, height: 50 }} />
    );

    const eHandle = container.querySelector('[data-resize-handle="e"]')!;

    // Start drag from x=0
    fireEvent.mouseDown(eHandle, { clientX: 0, clientY: 0, bubbles: true });
    // End drag — moved 28px right → new width = 128px → nearest token = "spacing.32" (8rem = 128px)
    fireEvent.mouseUp(window, { clientX: 28, clientY: 0 });

    expect(applySpy).toHaveBeenCalledTimes(1);
    const mutation: any = applySpy.mock.calls[0][0];
    expect(mutation.kind).toBe("set-style");
    expect(mutation.key).toBe("width");
    expect(mutation.value).toBe("spacing.32");
  });
});
