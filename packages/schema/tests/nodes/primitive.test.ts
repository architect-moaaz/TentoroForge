import { describe, it, expect } from "vitest";
import { PrimitiveNode } from "../../src/nodes/primitive";

describe("Box", () => {
  it("accepts box with style and children placeholder", () => {
    expect(() =>
      PrimitiveNode.parse({ id: "n1", type: "Box", style: { padding: "spacing.4" }, children: [] })
    ).not.toThrow();
  });
});

describe("Text", () => {
  it("accepts inline text content via props.content", () => {
    expect(() =>
      PrimitiveNode.parse({ id: "n2", type: "Text", props: { content: "hello" } })
    ).not.toThrow();
  });
  it("accepts content via bind instead of props", () => {
    expect(() =>
      PrimitiveNode.parse({ id: "n3", type: "Text", bind: { source: "x", path: "y" } })
    ).not.toThrow();
  });
  it("rejects when neither content nor bind given", () => {
    expect(() => PrimitiveNode.parse({ id: "n4", type: "Text" })).toThrow();
  });
});

describe("Image", () => {
  it("requires src and alt", () => {
    expect(() => PrimitiveNode.parse({ id: "n5", type: "Image", props: { src: "/x.png" } })).toThrow(/alt/);
    expect(() =>
      PrimitiveNode.parse({ id: "n6", type: "Image", props: { src: "/x.png", alt: "x" } })
    ).not.toThrow();
  });
});
