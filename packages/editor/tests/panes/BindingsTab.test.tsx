import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Properties } from "../../src/panes/Properties/Properties";
import { createEditorStore } from "../../src/state/store";

const reg = { has: () => false, get: () => undefined } as any;

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  dataSources: [{ name: "products", entity: "Product", op: "list" }],
  root: { id: "r", type: "Text", props: { content: "x" } },
});

describe("Bindings tab", () => {
  it("shows data source picker + path + visibleIf + workflow on click", async () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    store.getState().selectNode("r");
    render(<Properties store={store} registry={reg} tokens={{} as any} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "bindings" }));
    expect(screen.getByLabelText(/data source/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/visibleif/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/onclick workflow/i)).toBeInTheDocument();
  });

  it("editing visibleIf fires set-visible-if", async () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    store.getState().selectNode("r");
    render(<Properties store={store} registry={reg} tokens={{} as any} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "bindings" }));
    const input = screen.getByLabelText(/visibleif/i);
    await user.clear(input);
    await user.type(input, "user.role == 'admin'");
    expect((store.getState().pages["x"].schema.root as any).visibleIf).toBe("user.role == 'admin'");
  });
});
