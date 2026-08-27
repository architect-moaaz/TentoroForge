import { describe, it, expect } from "vitest";
import { LayoutNode, StackNode, GridNode } from "../../src/nodes/layout";

const validStack = {
  id: "n1",
  type: "Stack",
  props: { direction: "vertical", gap: "spacing.4", align: "start" },
  children: [],
};

describe("StackNode", () => {
  it("accepts a valid stack", () => {
    expect(() => StackNode.parse(validStack)).not.toThrow();
  });
  it("requires id", () => {
    const { id, ...rest } = validStack;
    expect(() => StackNode.parse(rest)).toThrow(/id/);
  });
  // Gap validation moved out of the schema layer — TokenRef is now permissive.
  // Raw values pass parse; leaf-token resolution happens at render time.
  it("accepts mixed gap forms (validation deferred to runtime resolver)", () => {
    expect(() =>
      StackNode.parse({ ...validStack, props: { ...validStack.props, gap: "16px" } }),
    ).not.toThrow();
    expect(() =>
      StackNode.parse({ ...validStack, props: { ...validStack.props, gap: "lg" } }),
    ).not.toThrow();
  });
});

describe("LayoutNode discriminated union", () => {
  it("dispatches on type", () => {
    expect(LayoutNode.parse(validStack).type).toBe("Stack");
    expect(
      LayoutNode.parse({ id: "n2", type: "Spacer", props: { size: "spacing.6" } }).type
    ).toBe("Spacer");
  });
});

describe("GridNode equalRows / equalCols (v4 spike CSS fix)", () => {
  // Codifies the iteration-3 v4 spike CSS fix as schema props so future
  // generations can declare layout-evenness intent (and the renderer
  // guarantees the CSS) instead of relying on hand-injected globals.css
  // patches.
  it("accepts equalRows + equalCols as optional booleans", () => {
    const r = GridNode.safeParse({
      id: "g",
      type: "Grid",
      props: { columns: 4, equalRows: true, equalCols: true },
      children: [],
    });
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.props.equalRows).toBe(true);
      expect(r.data.props.equalCols).toBe(true);
    }
  });

  it("remains valid without the new props (backward-compat)", () => {
    const r = GridNode.safeParse({
      id: "g",
      type: "Grid",
      props: { columns: 3 },
      children: [],
    });
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.props.equalRows).toBeUndefined();
      expect(r.data.props.equalCols).toBeUndefined();
    }
  });

  it("rejects non-boolean equalRows (strict mode keeps invariants)", () => {
    const r = GridNode.safeParse({
      id: "g",
      type: "Grid",
      props: { columns: 4, equalRows: "yes" },
      children: [],
    });
    expect(r.success).toBe(false);
  });
});
