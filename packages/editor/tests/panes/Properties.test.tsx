import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { Properties } from "../../src/panes/Properties/Properties";
import { createEditorStore } from "../../src/state/store";

const reg = {
  has: (n: string) => n === "Button",
  get: (n: string) => n === "Button" ? {
    name: "Button", component: () => null,
    propsSchema: z.object({ label: z.string(), variant: z.enum(["primary","secondary"]).default("primary") }).strict(),
    category: "interactive", acceptsChildren: false,
  } : undefined,
  validateProps: (n: string, p: any) => p,
} as any;

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  root: { id: "r", type: "Box", children: [
    { id: "btn", type: "Button", props: { label: "Save", variant: "primary" } },
  ]},
});

describe("Properties — Props tab", () => {
  it("shows props of the selected library node", () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    store.getState().selectNode("btn");
    render(<Properties store={store} registry={reg} tokens={{} as any} />);
    expect(screen.getByLabelText("label")).toHaveValue("Save");
    expect(screen.getByLabelText("variant")).toHaveValue("primary");
  });

  it("editing a prop fires set-prop mutation", async () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    store.getState().selectNode("btn");
    render(<Properties store={store} registry={reg} tokens={{} as any} />);
    const user = userEvent.setup();
    const input = screen.getByLabelText("label");
    await user.clear(input);
    await user.type(input, "Submit");
    expect((store.getState().pages["x"].schema.root as any).children[0].props.label).toBe("Submit");
  });
});

describe("Properties — Style tab (StyleSlotEditor)", () => {
  it("clicking style tab shows StyleSlotEditor with spacing token picker", async () => {
    const store = createEditorStore();
    store.getState().openPage("x", page());
    store.getState().selectNode("r");
    render(<Properties store={store} registry={reg} tokens={{} as any} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "style" }));
    expect(document.querySelector("[data-style-slot-editor]")).not.toBeNull();
    expect(document.querySelector("[data-token-picker=\"spacing\"]")).not.toBeNull();
  });
});
