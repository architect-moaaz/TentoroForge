import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tree } from "../../src/panes/Tree/Tree";
import { createEditorStore } from "../../src/state/store";

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  root: { id: "r", type: "Stack", children: [
    { id: "h", type: "Heading", props: { content: "Title" } },
    { id: "b", type: "Box", children: [
      { id: "t", type: "Text", props: { content: "x" } },
    ]},
  ]},
});

describe("Tree", () => {
  it("renders a node entry per node in the schema", () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    render(<Tree store={store} />);
    expect(screen.getByText("Stack")).toBeInTheDocument();
    expect(screen.getByText("Heading")).toBeInTheDocument();
    expect(screen.getByText("Box")).toBeInTheDocument();
    expect(screen.getByText("Text")).toBeInTheDocument();
  });

  it("clicking a tree entry selects the node", async () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    render(<Tree store={store} />);
    const user = userEvent.setup();
    await user.click(screen.getByText("Heading"));
    expect(store.getState().pages["x"].selection).toEqual(["h"]);
  });
});
