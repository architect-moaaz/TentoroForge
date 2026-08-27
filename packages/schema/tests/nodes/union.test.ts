import { describe, it, expect } from "vitest";
import { Node } from "../../src/nodes";

describe("Node union", () => {
  it("accepts each bucket via discriminator", () => {
    expect(() => Node.parse({ id: "1", type: "Stack", props: { gap: "spacing.2" }, children: [] })).not.toThrow();
    expect(() => Node.parse({ id: "2", type: "Box", children: [] })).not.toThrow();
    expect(() => Node.parse({ id: "3", type: "Button", props: { label: "x" } })).not.toThrow();
    expect(() =>
      Node.parse({
        id: "4",
        type: "Repeat",
        props: { source: "x" },
        children: [{ id: "r", type: "Text", props: { content: "y" } }],
      })
    ).not.toThrow();
    expect(() => Node.parse({ id: "5", type: "Slot", props: { name: "main" } })).not.toThrow();
  });

  it("rejects unknown shapes", () => {
    expect(() => Node.parse({ id: "x", type: "Stack" })).not.toThrow(); // children defaults
    expect(() => Node.parse({ id: "x", type: "Image" })).toThrow();    // missing required src/alt
  });
});
