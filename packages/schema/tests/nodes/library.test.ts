import { describe, it, expect } from "vitest";
import { LibraryNode } from "../../src/nodes/library";

describe("LibraryNode", () => {
  it("accepts an arbitrary component name (registry validates props later)", () => {
    expect(() =>
      LibraryNode.parse({ id: "b1", type: "Button", props: { variant: "primary", label: "Save" } })
    ).not.toThrow();
  });
  it("forbids type names that collide with reserved buckets", () => {
    expect(() => LibraryNode.parse({ id: "x", type: "Stack", props: {} })).toThrow();
    expect(() => LibraryNode.parse({ id: "x", type: "Box", props: {} })).toThrow();
    expect(() => LibraryNode.parse({ id: "x", type: "Repeat", props: {} })).toThrow();
    expect(() => LibraryNode.parse({ id: "x", type: "Slot", props: {} })).toThrow();
  });
});
