import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { Editor } from "../../src/Editor";

const productList = {
  schemaVersion: "1",
  id: "products/list",
  route: "/products",
  root: {
    id: "rA",
    type: "Heading",
    props: { level: 1, content: "Products" },
  },
};

const customerList = {
  schemaVersion: "1",
  id: "customers/list",
  route: "/customers",
  root: {
    id: "rB",
    type: "Heading",
    props: { level: 1, content: "Customers" },
  },
};

const reg = {
  list: () => [
    {
      name: "Heading",
      category: "static",
      acceptsChildren: false,
      propsSchema: z
        .object({ level: z.number(), content: z.string() })
        .strict(),
    },
  ],
  has: (n: string) => n === "Heading",
  get: (n: string) =>
    n === "Heading"
      ? {
          name: "Heading",
          component: ({ content }: any) => <h1>{content}</h1>,
          propsSchema: z
            .object({ level: z.number(), content: z.string() })
            .strict(),
          category: "static",
          acceptsChildren: false,
        }
      : undefined,
  validateProps: (_n: string, p: any) => p,
} as any;

const tokens = {
  colors: {},
  spacing: {},
  typography: {},
  radii: {},
  shadows: {},
} as any;

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("multi-page flow", () => {
  it("opens two pages, switches, edit on one preserved when switching back", async () => {
    let savedPayload: any = null;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (typeof url === "string" && url.includes("/api/editor/pages")) {
          return new Response(
            JSON.stringify({ paths: ["products/list", "customers/list"] }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        if (
          typeof url === "string" &&
          url.includes("path=products%2Flist")
        ) {
          return new Response(JSON.stringify({ schema: productList }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (
          typeof url === "string" &&
          url.includes("path=customers%2Flist")
        ) {
          return new Response(JSON.stringify({ schema: customerList }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (typeof url === "string" && url.includes("/api/editor/save")) {
          savedPayload = JSON.parse(init!.body as string);
          return new Response(
            JSON.stringify({
              ok: true,
              savedSchema: savedPayload.schema,
              suggestions: [],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        return new Response("404", { status: 404 });
      })
    );

    render(
      <Editor
        initialSchemaPath="products/list"
        registry={reg}
        tokens={tokens}
      />
    );

    // Wait for products/list to load
    await waitFor(
      () => expect(screen.getByText("Products")).toBeInTheDocument(),
      { timeout: 3000 }
    );

    // Edit the products heading via Properties panel
    const heading = document.querySelector(
      '[data-node-id="rA"]'
    ) as HTMLElement;
    expect(heading).not.toBeNull();
    await userEvent.click(heading);

    const contentInput = await screen.findByLabelText(
      "content",
      {},
      { timeout: 3000 }
    );
    await userEvent.clear(contentInput);
    await userEvent.type(contentInput, "All Products");

    // Verify the canvas now shows the edited value
    await waitFor(
      () =>
        expect(
          document.querySelector('[data-node-id="rA"]')?.textContent
        ).toBe("All Products"),
      { timeout: 3000 }
    );

    // Open customers/list via Explorer.
    // Explorer renders "products" folder first (because stub returns products first),
    // then "customers" folder. Both have a leaf named "list".
    // Find the "list" leaf inside the "customers" details element.
    const customersDetails = screen.getByText("customers").closest("details");
    expect(customersDetails).not.toBeNull();
    const customersListLeaf = within(customersDetails!).getByText("list");
    await userEvent.click(customersListLeaf);

    // Wait for customers/list to load
    await waitFor(
      () => expect(screen.getByText("Customers")).toBeInTheDocument(),
      { timeout: 3000 }
    );

    // Switch back to products/list via the tab strip
    const productsTab = screen.getByText("products/list");
    await userEvent.click(productsTab);

    // Edit should be preserved — the canvas shows "All Products"
    await waitFor(
      () => {
        const el = document.querySelector(
          '[data-node-id="rA"]'
        ) as HTMLElement;
        expect(el).not.toBeNull();
        expect(el.textContent).toBe("All Products");
      },
      { timeout: 3000 }
    );
  });

  it("empty state shows when no page is open", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ paths: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    );

    render(<Editor registry={reg} tokens={tokens} />);

    // Should see empty state prompt
    await waitFor(() =>
      expect(
        screen.getByText(/open a page from the explorer/i)
      ).toBeInTheDocument()
    );
  });
});
