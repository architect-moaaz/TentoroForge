import { starterRegistry } from "@forge/registry";

/**
 * Pure logic behind <EmptyNodeHints>. Kept out of the component so the two
 * decisions that actually matter — "is this node showing the user nothing?" and
 * "what should it tell them to do?" — are unit-testable without a DOM canvas.
 */

/** Fixed-position box for one hint, in screen px. */
export interface HintBox {
  key: string;
  nodeId: string;
  type: string;
  /** Short line telling the user what this is and what to do next. */
  label: string;
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * The editor creates these; the user never drags one, and GridGuides already
 * draws a dashed outline for every cell of a fixed grid. A hint on top of that
 * would be a second dashed box saying the same thing four times over.
 */
const NEVER_HINT = new Set(["GridCell"]);

/**
 * Elements that put ink on the screen without contributing text. A node whose
 * subtree contains one of these is showing the user SOMETHING, even if we
 * cannot say what — an Avatar's <img>, a Gauge's <svg>, a Checkbox's <input>,
 * a Divider's <hr>. Deliberately conservative: a false "not empty" costs the
 * user nothing, while a hint drawn over a component that is in fact rendering
 * would be worse than the blank box we are fixing.
 */
const INK_SELECTOR =
  "img,svg,canvas,video,iframe,picture,input,select,textarea,hr,[data-file-upload],[data-qrcode]";

/**
 * True when this element's subtree renders nothing a user can see.
 *
 * A node that CONTAINS other schema nodes is never empty by this test even if
 * all of them are blank: each child carries its own `data-node-id` and reports
 * itself, so the hint lands on the innermost thing that is actually missing
 * content rather than stacking one label per level of nesting.
 */
export function isVisuallyEmpty(box: Element): boolean {
  if (box.querySelector("[data-node-id]")) return false;
  if ((box.textContent ?? "").trim() !== "") return false;
  if (box.querySelector(INK_SELECTOR)) return false;
  return true;
}

/**
 * Walk through `display: contents` wrappers to the element that generates a
 * layout box. LibraryDispatcher wraps every library component in one, and a
 * contents element has no box to measure or draw over. Mirrors the identical
 * helpers in SelectionOverlay and useDrop.
 */
export function resolveBoxEl(el: HTMLElement | null): HTMLElement | null {
  if (!el) return null;
  if (typeof getComputedStyle !== "function") return el;
  if (getComputedStyle(el).display !== "contents") return el;
  for (const child of Array.from(el.children) as HTMLElement[]) {
    const inner = resolveBoxEl(child);
    if (inner) return inner;
  }
  return null;
}

/**
 * The prop a user has to fill in to make this component show something.
 *
 * Picks the first declared prop whose registry `control` is one of the
 * content-bearing kinds and whose value on the node is still empty. That is a
 * far better instruction than the component description for exactly the
 * components the audit found rendering an empty box — a Table needs `columns`,
 * a Chart needs `series`, a RadioGroup needs `options`.
 */
const CONTENT_CONTROLS = new Set(["actionPicker", "binding", "options", "json"]);

function isBlank(v: unknown): boolean {
  return (
    v === undefined ||
    v === null ||
    v === "" ||
    (Array.isArray(v) && v.length === 0)
  );
}

export function missingContentProp(
  type: string,
  props: Record<string, unknown> | undefined,
): string | null {
  const entry = (starterRegistry as Record<string, any>)[type];
  const declared = entry?.props as Record<string, { control?: string }> | undefined;
  if (!declared) return null;
  for (const [name, def] of Object.entries(declared)) {
    if (!CONTENT_CONTROLS.has(def?.control ?? "")) continue;
    if (isBlank(props?.[name])) return name;
  }
  return null;
}

/**
 * The hint line for one empty node.
 *
 * Three registers, in order of how actionable they are:
 *   1. a container → the thing to do is drop something into it;
 *   2. a leaf with an unfilled content prop → name that prop;
 *   3. anything else → fall back to the registry's own one-line description,
 *      which at least answers "what did I just drop?".
 */
export function hintFor(
  type: string,
  props?: Record<string, unknown>,
): string | null {
  if (NEVER_HINT.has(type)) return null;
  const entry = (starterRegistry as Record<string, any>)[type];
  if (!entry) return null;
  if (entry.slots?.type && entry.slots.type !== "leaf") {
    return `${type} — empty. Drag a component in here.`;
  }
  const prop = missingContentProp(type, props);
  if (prop) return `${type} — set “${prop}” in the Properties panel.`;
  const desc = typeof entry.description === "string" ? entry.description : "";
  return desc ? `${type} — ${desc}` : `${type} — nothing to show yet.`;
}
