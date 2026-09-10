import { starterRegistry } from "@forge/registry";
import { buildDefaultRegistry } from "@tentoroforge/library";

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
  /**
   * True when the node's own box was too small to carry a label and the
   * overlay padded it out to `MIN_HINT_W` x `MIN_HINT_H`. The node is
   * invisible on the canvas; the hint is the only thing marking where it is.
   */
  ghost?: boolean;
}

/**
 * Smallest rectangle a hint can be drawn in and still be read. Anything the
 * canvas lays out smaller than this — including the 0-height and 0x0 nodes
 * that were previously skipped entirely — is padded up to it.
 */
export const MIN_HINT_W = 120;
export const MIN_HINT_H = 16;

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
 * layout box. Re-exported under the name this module's callers already use;
 * the implementation is shared — see layout-box.ts for why it stopped being
 * six private copies.
 */
export { resolveLayoutBox as resolveBoxEl } from "./layout-box";

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

/* ---------------------------------------------------------------------------
 * THE PROP THE COMPONENT ITSELF REQUIRES — read off its Zod schema.
 *
 * Audit rows 27/28 are one bug: the hint was derived from the REGISTRY
 * descriptor, so it named whichever descriptor happened to exist rather than
 * whichever prop the component cannot render without. Stepper was told to
 * "set bind" (`z.string().optional()` — never the problem) while the prop it
 * actually needs, `steps: z.array(...)`, went unmentioned; Carousel / List /
 * Tree / DescriptionList / ValidationChecklist had no content descriptor at
 * all and so fell through to the palette blurb, naming no prop.
 *
 * The library registry carries every component's own `propsSchema`, which is
 * the contract the component and the page validator are both written against.
 * Reading required-ness off THAT is correct for all 133 components and stays
 * correct when a component's schema changes — there is no per-component table
 * here and there must never be one.
 * ------------------------------------------------------------------------- */

/** name → the component's own Zod props schema. Built once, lazily. */
let propsSchemaByName: Map<string, any> | null = null;

function propsSchemaFor(type: string): any | null {
  if (!propsSchemaByName) {
    propsSchemaByName = new Map();
    try {
      // Built on first hint, not at module load: the registry instantiates
      // every component in the library and nothing needs it until a node
      // turns out to be empty.
      for (const e of buildDefaultRegistry().list()) {
        if (e?.name && e.propsSchema) propsSchemaByName.set(e.name, e.propsSchema);
      }
    } catch {
      // No library at hand — the registry-descriptor path below still applies.
    }
  }
  return propsSchemaByName.get(type) ?? null;
}

/**
 * Peel the wrappers Zod puts around a prop's real type.
 *
 * `optional()` / `default()` / `catch()` mean "the component can render
 * without this"; `nullable()`, `preprocess()`, `brand()` and friends do not.
 * Purely structural — it never looks at a prop's name.
 */
function unwrapProp(schema: any): { required: boolean; inner: any } {
  let s = schema;
  let required = true;
  const seen = new Set<any>();
  while (s && s._def && !seen.has(s)) {
    seen.add(s);
    const t = s._def.typeName;
    if (t === "ZodOptional" || t === "ZodDefault" || t === "ZodCatch") {
      required = false;
      s = s._def.innerType;
    } else if (t === "ZodNullable" || t === "ZodReadonly") {
      s = s._def.innerType;
    } else if (t === "ZodEffects") {
      s = s._def.schema;
    } else if (t === "ZodBranded") {
      s = s._def.type;
    } else if (t === "ZodPipeline") {
      s = s._def.in;
    } else if (t === "ZodLazy") {
      try { s = s._def.getter(); } catch { s = null; }
    } else {
      break;
    }
  }
  return { required, inner: s };
}

/**
 * A prop whose type is a list is the shape content arrives in — `steps`,
 * `items`, `images`, `columns`, `options`, `actions`. Records are excluded on
 * purpose: `style: z.record(...)` is a styling slot on nearly every component
 * and is never the thing a user is missing.
 */
function isListProp(inner: any): boolean {
  const t = inner?._def?.typeName;
  if (t === "ZodArray") return true;
  if (t === "ZodUnion" || t === "ZodDiscriminatedUnion") {
    const opts: any[] = inner._def.options ?? [];
    return opts.some((o) => isListProp(unwrapProp(o).inner));
  }
  return false;
}

/** The `{ key: schema }` map of an object schema, through any root wrappers. */
function objectShape(schema: any): Record<string, any> | null {
  const { inner } = unwrapProp(schema);
  if (inner?._def?.typeName !== "ZodObject") return null;
  const shape = inner._def.shape;
  const resolved = typeof shape === "function" ? shape() : shape;
  return resolved && typeof resolved === "object" ? resolved : null;
}

/**
 * The prop this node is missing, according to the component's own schema.
 *
 * Ranked, not first-match, because declaration order is not importance order:
 *   1. required AND list-shaped — the content the component exists to render;
 *   2. required — anything else it cannot do without;
 *   3. list-shaped with a default of `[]` — "no items" is a legal value but an
 *      empty box is never what the user wanted.
 * Blank means unset: `undefined`, `null`, `""` or `[]`.
 */
export function schemaMissingProp(
  type: string,
  props: Record<string, unknown> | undefined,
): string | null {
  const shape = objectShape(propsSchemaFor(type));
  if (!shape) return null;
  let requiredList: string | null = null;
  let requiredAny: string | null = null;
  let emptyList: string | null = null;
  for (const [name, def] of Object.entries(shape)) {
    if (!isBlank(props?.[name])) continue;
    const { required, inner } = unwrapProp(def);
    const list = isListProp(inner);
    if (required && list) requiredList ??= name;
    else if (required) requiredAny ??= name;
    else if (list) emptyList ??= name;
  }
  return requiredList ?? requiredAny ?? emptyList;
}

/** Does the Properties panel actually offer a control for this prop? */
function hasControlFor(type: string, prop: string): boolean {
  const declared = (starterRegistry as Record<string, any>)[type]?.props;
  return !!declared && Object.prototype.hasOwnProperty.call(declared, prop);
}

/**
 * The hint line for one empty node.
 *
 * In order of how actionable it is:
 *   1. a container → the thing to do is drop something into it;
 *   2. the prop the component's own schema says it needs → name that prop,
 *      and say so plainly when the panel has no control for it (that is a
 *      registry gap, and pretending otherwise sends the user hunting);
 *   3. a registry content descriptor left blank → name that;
 *   4. anything else → the registry's own one-line description, which at
 *      least answers "what did I just drop?".
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
  const required = schemaMissingProp(type, props);
  if (required) {
    return hasControlFor(type, required)
      ? `${type} — set “${required}” in the Properties panel.`
      : `${type} — needs “${required}”, which has no control yet.`;
  }
  const prop = missingContentProp(type, props);
  if (prop) return `${type} — set “${prop}” in the Properties panel.`;
  const desc = typeof entry.description === "string" ? entry.description : "";
  return desc ? `${type} — ${desc}` : `${type} — nothing to show yet.`;
}
