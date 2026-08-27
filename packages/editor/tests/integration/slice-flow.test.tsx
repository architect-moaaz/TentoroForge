import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { Editor } from "../../src/Editor";

// Inline registry mock — no import from @tentoroforge/library needed
const reg = {
  list: () => [
    {
      name: "Button",
      category: "interactive",
      acceptsChildren: false,
      propsSchema: z.object({ label: z.string(), workflow: z.string().optional() }).strict(),
    },
    {
      name: "Heading",
      category: "static",
      acceptsChildren: false,
      propsSchema: z.object({ level: z.number(), content: z.string() }).strict(),
    },
  ],
  has: (n: string) => ["Button", "Heading", "Stack", "Box", "Text"].includes(n),
  get: (n: string) => {
    if (n === "Button")
      return {
        name: "Button",
        component: ({ label }: any) => <button>{label}</button>,
        propsSchema: z.object({ label: z.string(), workflow: z.string().optional() }).strict(),
        category: "interactive",
        acceptsChildren: false,
      };
    if (n === "Heading")
      return {
        name: "Heading",
        component: ({ content }: any) => <h1>{content}</h1>,
        propsSchema: z.object({ level: z.number(), content: z.string() }).strict(),
        category: "static",
        acceptsChildren: false,
      };
    return undefined;
  },
  validateProps: (_n: string, p: any) => p,
} as any;

// Inline token mock
const tokens = { colors: {}, spacing: {}, typography: {}, radii: {}, shadows: {} } as any;

// Fixture schema — uses built-in types (Stack, Box) + library type (Heading)
const productListSchema = {
  schemaVersion: "1",
  id: "products/list",
  route: "/products",
  root: {
    id: "page-root",
    type: "Stack",
    children: [
      {
        id: "header",
        type: "Box",
        children: [
          { id: "title", type: "Heading", props: { level: 1, content: "Products" } },
        ],
      },
    ],
  },
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("Phase 2A canonical user story (slice-flow)", () => {
  it("loads schema, edits a node prop, saves, then undoes", async () => {
    let savedPayload: any = null;

    // Mock fetch for load and save endpoints
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (typeof url === "string" && url.includes("/api/editor/pages")) {
          return new Response(JSON.stringify({ paths: ["products/list"] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (typeof url === "string" && url.includes("/api/editor/load")) {
          return new Response(JSON.stringify({ schema: productListSchema }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (typeof url === "string" && url.includes("/api/editor/save")) {
          savedPayload = JSON.parse((init as RequestInit).body as string);
          return new Response(
            JSON.stringify({
              ok: true,
              savedSchema: savedPayload.schema,
              suggestions: [],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        return new Response("Not found", { status: 404 });
      })
    );

    // Step 1: Mount <Editor initialSchemaPath="products/list" />
    render(<Editor initialSchemaPath="products/list" registry={reg} tokens={tokens} />);

    // Step 2: Wait for load — "Products" heading should appear
    await waitFor(() => expect(screen.getByText("Products")).toBeInTheDocument(), {
      timeout: 3000,
    });

    // Step 3: Click the title node to select it
    // data-node-id="title" is emitted by LibraryDispatcher's wrapper span
    const titleEl = document.querySelector('[data-node-id="title"]') as HTMLElement;
    expect(titleEl).not.toBeNull();
    await userEvent.click(titleEl);

    // Step 4: Edit the `content` prop in Properties panel
    // PropsTab renders <label for="prop-content">content</label> + <input id="prop-content" />
    // Use fireEvent.change so the entire new value is dispatched as a single mutation
    // (userEvent.type fires one mutation per keystroke, making undo non-deterministic).
    const contentInput = await screen.findByLabelText("content");
    fireEvent.change(contentInput, { target: { value: "All Products" } });

    // Step 5: Click Save
    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    await userEvent.click(saveBtn);

    // Step 6: Verify save endpoint called with modified schema
    await waitFor(() => expect(savedPayload).not.toBeNull(), { timeout: 3000 });
    expect(savedPayload.path).toBe("products/list");
    const titleNode = savedPayload.schema.root.children[0].children[0];
    expect(titleNode.props.content).toBe("All Products");

    // Step 7: Trigger Cmd+Z; verify undo restored the original content
    const user = userEvent.setup();
    await user.keyboard("{Meta>}z{/Meta}");

    // After undo the title node content reverts to "Products"
    await waitFor(() => {
      const el = document.querySelector('[data-node-id="title"]') as HTMLElement;
      expect(el).not.toBeNull();
      expect(el.textContent).toBe("Products");
    });
  });
});
