/**
 * Where a dropped thing lands — one rule for the Layers list and the canvas,
 * so dragging onto a layer and onto the same element on the page agree.
 */
import type { ModelNode, PageModel } from "../types";

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

/**
 * Where moving `movingId` to `where` the target puts it, as the parent and
 * index the `move` op takes — or null when it cannot go there: onto itself,
 * into its own descendants, or inside something that holds no children.
 */
export function moveLanding(model: PageModel, movingId: string, targetId: string, where: DropWhere): { parentId: string; index: number | null } | null {
  const target = model.nodes[targetId];
  const moving = model.nodes[movingId];
  if (!target || !moving || targetId === movingId) return null;
  for (let p = target.parent; p; p = model.nodes[p]?.parent ?? null) if (p === movingId) return null;
  if (where === "inside") return canHold(target) ? { parentId: target.id, index: null } : null;
  if (!target.parent) return null;
  return { parentId: target.parent, index: target.index + (where === "after" ? 1 : 0) };
}
