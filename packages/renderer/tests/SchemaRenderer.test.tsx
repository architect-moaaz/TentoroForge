import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import { SchemaRenderer } from "../src/SchemaRenderer";

describe("SchemaRenderer", () => {
  it("validates the page, resolves data, renders", async () => {
    const dataEngineMock = {
      run: async (_s: any) => ({ items: [{ id: 1, name: "Widget" }] }),
    };
    const page = {
      schemaVersion: "1",
      id: "p",
      route: "/",
      dataSources: [{ name: "products", entity: "Product", op: "list" }],
      root: {
        id: "rep",
        type: "Repeat",
        props: { source: "products", path: "items", as: "item", keyPath: "id" },
        children: [{ id: "name", type: "Text", bind: { source: "item", path: "name" } }],
      },
    };
    const el = await SchemaRenderer({ page: page as any, dataEngine: dataEngineMock } as any);
    const html = renderToString(el as any);
    expect(html).toContain("Widget");
  });

  it("throws on invalid schema (missing root)", async () => {
    await expect(
      SchemaRenderer({
        page: { schemaVersion: "1", id: "p", route: "/" } as any,
        dataEngine: { run: async () => ({}) },
      } as any)
    ).rejects.toThrow();
  });
});
