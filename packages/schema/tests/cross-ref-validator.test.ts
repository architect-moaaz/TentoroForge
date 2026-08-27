import { describe, it, expect } from "vitest";
import { validateCrossRefs, type ValidationContext } from "../src/cross-ref-validator";

const ctx: ValidationContext = {
  entities: new Set(["Product", "Customer"]),
  workflows: new Set(["createProduct", "deleteProduct"]),
  libraryNames: new Set(["Button", "Card", "Form"]),
  tokens: new Set(["primary.500", "spacing.4"]),
};

describe("validateCrossRefs", () => {
  it("returns no errors for a valid schema", () => {
    const schema: any = {
      schemaVersion: "1", id: "p", route: "/",
      dataSources: [{ name: "products", entity: "Product", op: "list" }],
      root: {
        id: "r", type: "Card",
        on: { click: { workflow: "deleteProduct", args: { id: "products.items[0].id" } } },
        style: { color: "primary.500" },
        children: [],
      },
    };
    expect(validateCrossRefs(schema, ctx)).toEqual([]);
  });

  it("flags unknown entity in data source", () => {
    const schema: any = {
      schemaVersion: "1", id: "p", route: "/",
      dataSources: [{ name: "x", entity: "Order", op: "list" }],
      root: { id: "r", type: "Card", children: [] },
    };
    const errs = validateCrossRefs(schema, ctx);
    expect(errs.some(e => e.message.includes("Order"))).toBe(true);
  });

  it("flags unknown workflow ref", () => {
    const schema: any = {
      schemaVersion: "1", id: "p", route: "/",
      root: {
        id: "r", type: "Card",
        on: { click: { workflow: "missingFlow" } },
        children: [],
      },
    };
    const errs = validateCrossRefs(schema, ctx);
    expect(errs.some(e => e.message.includes("missingFlow"))).toBe(true);
  });

  it("flags unknown library component", () => {
    const schema: any = {
      schemaVersion: "1", id: "p", route: "/",
      root: { id: "r", type: "MysteryThing", children: [] },
    };
    const errs = validateCrossRefs(schema, ctx);
    expect(errs.some(e => e.message.includes("MysteryThing"))).toBe(true);
  });

  it("flags unknown token reference", () => {
    const schema: any = {
      schemaVersion: "1", id: "p", route: "/",
      root: { id: "r", type: "Card", style: { color: "weird.999" }, children: [] },
    };
    const errs = validateCrossRefs(schema, ctx);
    expect(errs.some(e => e.message.includes("weird.999"))).toBe(true);
  });
});
