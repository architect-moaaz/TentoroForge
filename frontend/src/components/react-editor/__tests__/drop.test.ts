import { describe, expect, it } from "vitest";

import { canHold, dropPosition } from "../lib/drop";
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
