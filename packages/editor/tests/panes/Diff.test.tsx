import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Diff } from "../../src/panes/Diff/Diff";
import { createEditorStore } from "../../src/state/store";
import { buildSetProp } from "../../src/state/mutations";

const page = (): any => ({
  schemaVersion: "1",
  id: "p",
  route: "/",
  root: { id: "r", type: "Text", props: { content: "x" } },
});

describe("Diff", () => {
  it("shows empty state when clean", () => {
    const store = createEditorStore();
    store.getState().openPage("a", page());
    render(<Diff store={store} />);
    expect(screen.getByText(/no unsaved changes/i)).toBeInTheDocument();
  });

  it("lists mutations since last save", () => {
    const store = createEditorStore();
    store.getState().openPage("a", page());
    store.getState().apply(buildSetProp("r", "content", "y", store.getState().pages["a"].schema));
    store.getState().apply(buildSetProp("r", "content", "z", store.getState().pages["a"].schema));
    render(<Diff store={store} />);
    expect(screen.getAllByText(/set-prop/i).length).toBe(2);
  });

  it("shows empty state when no page is open", () => {
    const store = createEditorStore();
    const { container } = render(<Diff store={store} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows empty state after markSaved", () => {
    const store = createEditorStore();
    store.getState().openPage("a", page());
    store.getState().apply(buildSetProp("r", "content", "y", store.getState().pages["a"].schema));
    store.getState().markSaved(store.getState().pages["a"].schema);
    render(<Diff store={store} />);
    expect(screen.getByText(/no unsaved changes/i)).toBeInTheDocument();
  });
});
