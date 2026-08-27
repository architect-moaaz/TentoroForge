import { describe, it, expect } from "vitest";
import { SlotNode } from "../../src/nodes/slot";

describe("SlotNode", () => {
  it("accepts a named slot with no children", () => {
    expect(() => SlotNode.parse({ id: "s1", type: "Slot", props: { name: "main" } })).not.toThrow();
  });
  it("requires name", () => {
    expect(() => SlotNode.parse({ id: "s2", type: "Slot", props: {} })).toThrow();
  });
});
