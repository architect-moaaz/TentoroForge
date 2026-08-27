import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { Properties } from "../../src/panes/Properties/Properties";
import { createEditorStore } from "../../src/state/store";

const reg = {
  has: (n: string) => n === "Heading",
  get: (n: string) =>
    n === "Heading"
      ? {
          name: "Heading",
          component: () => null,
          propsSchema: z
            .object({ level: z.number().default(1), content: z.string() })
            .strict(),
          category: "static",
          acceptsChildren: false,
        }
      : undefined,
  validateProps: (n: string, p: any) => p,
} as any;

const page = (): any => ({
  schemaVersion: "1",
  id: "p",
  route: "/",
  root: {
    id: "r",
    type: "Box",
    children: [
      { id: "h1", type: "Heading", props: { level: 1, content: "A" } },
      { id: "h2", type: "Heading", props: { level: 1, content: "B" } },
      { id: "h3", type: "Heading", props: { level: 2, content: "C" } },
    ],
  },
});

describe("Properties — multi-select", () => {
  it("shows common value when all selected agree", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("h1");
    store.getState().toggleSelection("h2");
    render(<Properties store={store} registry={reg} tokens={{} as any} />);
    // h1 and h2 both have level=1 → should show value "1"
    const levelInput = screen.getByLabelText("level") as HTMLInputElement;
    expect(levelInput.value).toBe("1");
  });

  it("shows mixed indicator when values differ", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("h1");
    store.getState().toggleSelection("h3");
    render(<Properties store={store} registry={reg} tokens={{} as any} />);
    // level differs (1 vs 2) → empty value + mixed indicator
    const levelInput = screen.getByLabelText(/level/) as HTMLInputElement;
    expect(levelInput.value).toBe("");
    // multiple "(mixed)" indicators may appear (one per differing prop + summary)
    expect(screen.getAllByText(/mixed/i).length).toBeGreaterThan(0);
  });

  it("editing a prop applies to all selected via composite", async () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("h1");
    store.getState().toggleSelection("h3");
    render(<Properties store={store} registry={reg} tokens={{} as any} />);
    const input = screen.getByLabelText("content") as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "Z");
    const root = store.getState().pages.p.schema.root as any;
    expect(root.children[0].props.content).toBe("Z");
    expect(root.children[2].props.content).toBe("Z");
  });
});
