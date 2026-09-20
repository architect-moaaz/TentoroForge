import { describe, expect, it } from "vitest";

import { canHold, dropPosition, moveLanding } from "../lib/drop";
import type { ModelNode } from "../types";

function node(type: string, extra: Partial<ModelNode> = {}): ModelNode {
  return {
    id: "n", parent: "root", index: 0, type, kind: "element", props: [], text: null, textEditable: false,
    inner: null, innerSpan: null, selfClosing: false, span: [0, 0], wrapperSpan: null, line: 1, endLine: 1,
    context: null, children: [], ...extra,
  } as ModelNode;
}

// One rule for a drop on a layer and a drop on the page, so the two agree.
describe("where a dropped palette item lands", () => {
  it("goes inside the middle of something that holds children, else by the nearer edge", () => {
    const card = node("Card", { kind: "component" });
    expect(dropPosition(card, 0.1)).toBe("before");
    expect(dropPosition(card, 0.5)).toBe("inside");
    expect(dropPosition(card, 0.9)).toBe("after");
  });

  it("never goes inside something that cannot hold children", () => {
    const input = node("Input", { kind: "component", selfClosing: true });
    expect(canHold(input)).toBe(false);
    expect(dropPosition(input, 0.5)).toBe("after");
    expect(dropPosition(node("hr"), 0.4)).toBe("before");
  });

  it("only goes inside the page's outermost element — there is nothing beside it", () => {
    expect(dropPosition(node("div", { parent: null }), 0.05)).toBe("inside");
    expect(dropPosition(node("div", { parent: null }), 0.95)).toBe("inside");
  });
});

// One rule for a move from the Layers list and a drag on the page, so the two agree.
describe("where a moved element lands", () => {
  const n = (id: string, type: string, parent: string | null, index: number, children: string[] = [], extra: Partial<ModelNode> = {}) =>
    node(type, { id, parent, index, children, ...extra });
  const model = {
    ok: true, roots: [{ id: "r0", owner: "View" }], imports: [], viewProps: [], viewParam: null, loadKeys: [], loadShapes: {},
    nodes: {
      r0: n("r0", "div", null, 0, ["r0.0", "r0.1", "r0.2"]),
      "r0.0": n("r0.0", "Card", "r0", 0, ["r0.0.0"], { kind: "component" }),
      "r0.0.0": n("r0.0.0", "p", "r0.0", 0),
      "r0.1": n("r0.1", "Input", "r0", 1, [], { kind: "component", selfClosing: true }),
      "r0.2": n("r0.2", "section", "r0", 2),
    },
  } as unknown as import("../types").PageModel;

  it("lands beside the target by its index, or inside it at the end", () => {
    expect(moveLanding(model, "r0.2", "r0.0", "before")).toEqual({ parentId: "r0", index: 0 });
    expect(moveLanding(model, "r0.2", "r0.0", "after")).toEqual({ parentId: "r0", index: 1 });
    expect(moveLanding(model, "r0.2", "r0.0", "inside")).toEqual({ parentId: "r0.0", index: null });
  });

  it("refuses itself, its own inside, and anything that holds no children", () => {
    expect(moveLanding(model, "r0.0", "r0.0", "after")).toBeNull();
    expect(moveLanding(model, "r0.0", "r0.0.0", "before")).toBeNull();
    expect(moveLanding(model, "r0.2", "r0.1", "inside")).toBeNull();
    expect(moveLanding(model, "r0.2", "r0", "before")).toBeNull();
    expect(moveLanding(model, "r0.2", "r0", "inside")).toEqual({ parentId: "r0", index: null });
  });
});
