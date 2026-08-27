import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toolbar } from "../../src/chrome/Toolbar";
import { createEditorStore } from "../../src/state/store";
import { buildSetProp } from "../../src/state/mutations";

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  root: { id: "r", type: "Text", props: { content: "x" } },
});

const PATH = "x";

describe("Toolbar", () => {
  it("save button triggers onSave callback", async () => {
    const store = createEditorStore();
    store.getState().openPage(PATH, page());
    const onSave = vi.fn();
    render(<Toolbar store={store} onSave={onSave} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalled();
  });

  it("undo button is disabled when history is empty", () => {
    const store = createEditorStore();
    store.getState().openPage(PATH, page());
    render(<Toolbar store={store} onSave={() => {}} />);
    expect(screen.getByRole("button", { name: /undo/i })).toBeDisabled();
  });

  it("undo button enabled after a mutation", () => {
    const store = createEditorStore();
    store.getState().openPage(PATH, page());
    store.getState().apply(buildSetProp("r", "content", "y", store.getState().pages[PATH].schema));
    render(<Toolbar store={store} onSave={() => {}} />);
    expect(screen.getByRole("button", { name: /undo/i })).not.toBeDisabled();
  });

  it("shows dirty indicator", () => {
    const store = createEditorStore();
    store.getState().openPage(PATH, page());
    store.getState().apply(buildSetProp("r", "content", "y", store.getState().pages[PATH].schema));
    render(<Toolbar store={store} onSave={() => {}} />);
    expect(screen.getByText(/dirty/i)).toBeInTheDocument();
  });

  it("shows selection count when more than 1 node selected", async () => {
    const multiPage = (): any => ({
      schemaVersion: "1", id: "p", route: "/",
      root: { id: "r", type: "Box", children: [
        { id: "a", type: "Text", props: { content: "A" } },
        { id: "b", type: "Text", props: { content: "B" } },
      ]},
    });
    const store = createEditorStore();
    store.getState().openPage(PATH, multiPage());
    render(<Toolbar store={store} onSave={() => {}} />);
    // No indicator when 0 nodes selected
    expect(screen.queryByText(/selected/i)).toBeNull();
    // Select two nodes (triggers Zustand subscription → re-render)
    await act(async () => {
      store.getState().selectNode("a");
      store.getState().toggleSelection("b");
    });
    expect(screen.getByText(/2 selected/i)).toBeInTheDocument();
  });
});
