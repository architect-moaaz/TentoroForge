import { describe, it, expect } from "vitest";
import { DataNode } from "../../src/nodes/data";

describe("Repeat", () => {
  it("requires source + item template", () => {
    expect(() =>
      DataNode.parse({
        id: "r1",
        type: "Repeat",
        props: { source: "products" },
        children: [{ id: "row", type: "Text", props: { content: "x" } }],
      })
    ).not.toThrow();
  });
  it("requires at least one child", () => {
    expect(() =>
      DataNode.parse({ id: "r2", type: "Repeat", props: { source: "products" }, children: [] })
    ).toThrow();
  });
});

describe("Conditional", () => {
  it("accepts when + then + optional else", () => {
    expect(() =>
      DataNode.parse({
        id: "c1",
        type: "Conditional",
        props: { when: "user.role == 'admin'" },
        children: [
          { id: "t", type: "Text", props: { content: "admin" } },
        ],
      })
    ).not.toThrow();
  });
});
