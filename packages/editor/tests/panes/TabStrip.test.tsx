import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TabStrip } from "../../src/panes/Tabs/TabStrip";
import { createEditorStore } from "../../src/state/store";
import { buildSetProp } from "../../src/state/mutations";

const pageA = (): any => ({ schemaVersion: "1", id: "a", route: "/", root: { id: "rA", type: "Box", children: [] } });
const pageB = (): any => ({ schemaVersion: "1", id: "b", route: "/", root: { id: "rB", type: "Box", children: [] } });

describe("TabStrip", () => {
  it("renders one tab per open page with active marker", () => {
    const store = createEditorStore();
    store.getState().openPage("a/list", pageA());
    store.getState().openPage("b/list", pageB());
    render(<TabStrip store={store} />);
    expect(screen.getByText("a/list")).toBeInTheDocument();
    expect(screen.getByText("b/list")).toBeInTheDocument();
    // current is b/list (last opened)
    expect(screen.getByText("b/list").closest('[data-active="true"]')).toBeTruthy();
  });

  it("clicking a tab switches currentPath", async () => {
    const store = createEditorStore();
    store.getState().openPage("a/list", pageA());
    store.getState().openPage("b/list", pageB());
    render(<TabStrip store={store} />);
    await userEvent.click(screen.getByText("a/list"));
    expect(store.getState().currentPath).toBe("a/list");
  });

  it("close button removes the tab", async () => {
    const store = createEditorStore();
    store.getState().openPage("a/list", pageA());
    render(<TabStrip store={store} />);
    await userEvent.click(screen.getByRole("button", { name: /close a\/list/i }));
    expect(Object.keys(store.getState().pages)).toEqual([]);
  });

  it("shows dirty dot when page is dirty", () => {
    const store = createEditorStore();
    const page = pageA();
    store.getState().openPage("a/list", page);
    // Mark it dirty by applying a mutation
    store.getState().apply({ kind: "set-prop", id: "rA", key: "x", value: "1", prevValue: undefined });
    render(<TabStrip store={store} />);
    expect(screen.getByLabelText("dirty")).toBeInTheDocument();
  });
});

const page = (): any => ({ schemaVersion: "1", id: "p", route: "/", root: { id: "r", type: "Text", props: { content: "x" } } });

describe("TabStrip dirty close confirm", () => {
  it("prompts confirm on dirty close; aborts on decline", async () => {
    const store = createEditorStore();
    store.getState().openPage("a", page());
    store.getState().apply(buildSetProp("r", "content", "y", store.getState().pages.a.schema));
    expect(store.getState().pages.a.saveState).toBe("dirty");

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<TabStrip store={store} />);
    await userEvent.click(screen.getByRole("button", { name: /close a/i }));
    expect(store.getState().pages.a).toBeDefined();   // not closed
    confirmSpy.mockRestore();
  });

  it("closes when user accepts confirm", async () => {
    const store = createEditorStore();
    store.getState().openPage("a", page());
    store.getState().apply(buildSetProp("r", "content", "y", store.getState().pages.a.schema));

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<TabStrip store={store} />);
    await userEvent.click(screen.getByRole("button", { name: /close a/i }));
    expect(store.getState().pages.a).toBeUndefined();
    confirmSpy.mockRestore();
  });
});
