/**
 * Where a dropped thing lands — one rule for the Layers list and the canvas,
 * so dragging onto a layer and onto the same element on the page agree.
 */
import type { ModelNode } from "../types";

/** Elements that never hold children. */
export const VOID = new Set(["input", "img", "br", "hr", "textarea", "select", "Input", "Textarea", "Separator", "Skeleton", "Checkbox"]);

export type DropWhere = "before" | "after" | "inside";

export function canHold(n: ModelNode): boolean {
  return !n.selfClosing && !VOID.has(n.type);
}

/**
 * From how far down the target the pointer is (0 = top edge, 1 = bottom): the
 * middle band of something that can hold children is "inside", otherwise the
 * nearer edge. The page's outermost element only takes things inside it.
 */
export function dropPosition(n: ModelNode, y: number): DropWhere {
  if (!n.parent) return "inside";
  if (canHold(n) && y > 0.3 && y < 0.7) return "inside";
  return y < 0.5 ? "before" : "after";
}
