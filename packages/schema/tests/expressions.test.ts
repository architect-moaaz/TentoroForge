import { describe, it, expect } from "vitest";
import { Expression, DataBinding, EventHandler } from "../src/expressions";

describe("Expression", () => {
  it("accepts non-empty strings", () => {
    expect(Expression.parse("user.role == 'admin'")).toBe("user.role == 'admin'");
  });
  it("rejects empty string", () => {
    expect(() => Expression.parse("")).toThrow();
  });
});

describe("DataBinding", () => {
  it("accepts source + path", () => {
    expect(() => DataBinding.parse({ source: "products", path: "items[0].name" })).not.toThrow();
  });
  it("requires both fields", () => {
    expect(() => DataBinding.parse({ source: "products" })).toThrow();
    expect(() => DataBinding.parse({ path: "x" })).toThrow();
  });
});

describe("EventHandler", () => {
  it("accepts workflow refs", () => {
    expect(() =>
      EventHandler.parse({ workflow: "deleteProduct", args: { id: "currentProduct.id" } })
    ).not.toThrow();
  });
  it("accepts navigate shorthand", () => {
    expect(() => EventHandler.parse({ navigate: "/products" })).not.toThrow();
  });
  it("rejects unrecognized shapes", () => {
    expect(() => EventHandler.parse({ run: "foo" })).toThrow();
    expect(() => EventHandler.parse({})).toThrow();
  });
  it("rejects empty-string args values", () => {
    expect(() =>
      EventHandler.parse({ workflow: "x", args: { id: "" } })
    ).toThrow();
  });
  it("accepts non-empty string, number, and boolean args values", () => {
    expect(() =>
      EventHandler.parse({ workflow: "x", args: { id: "currentProduct.id", count: 3, active: true } })
    ).not.toThrow();
  });
});
