/**
 * REGISTRY ↔ NODE-SCHEMA PARITY — a drift alarm for the defect class that keeps
 * coming back, one component at a time.
 *
 * The shape of the bug, seen three different ways in one audit round:
 *
 *   • `ContextMenu` / `DropdownMenu` / `Menubar` had no control for the ONE prop
 *     they exist to show, so the editor persisted `{"type":"Menubar","props":{}}`
 *     and the component rendered an empty bar nobody could fill in.
 *   • `Grid.padding` / `Grid.align` were live selects the renderer never read AND
 *     `V2GridNode.props` — which is `.strict()` — rejected outright.
 *   • Every input seeded `name: ""` against a `z.string().min(1)`, and `Skeleton`
 *     seeded `lines: 3` next to `variant: "rect"`, which its own cross-field
 *     refinement forbids.
 *
 * All three land in the same place: the editor writes page JSON that `PageV2`
 * refuses, the scaffold logs `schema validation failed … rendering raw`, and the
 * WHOLE page — not just the bad node — drops out of validated rendering. One bad
 * default takes its neighbours down with it.
 *
 * So this asserts the two registry-owned halves of the contract, per prop, with
 * no page assembly and no copy of the frontend's drop pipeline:
 *
 *   1. Every registry prop exists on the component's `.strict()` node props
 *      shape. A prop that does not is either dead (no reader) or needs the node
 *      schema widened — both are bugs, neither is silent any more.
 *   2. Every registry `default` is a value that prop's own schema accepts.
 *
 * KNOWN_GAPS is the list of instances that are real but NOT the registry's to
 * fix — the component implements the prop and the `.strict()` node schema is the
 * side that is too narrow. Each one is routed, and each one is spelled out so
 * the entry has to be deleted (not quietly grown) when the schema catches up.
 * A NEW name appearing in either failure list is a new bug.
 */
import { describe, it, expect } from "vitest";
import { NodeV2 } from "@tentoroforge/schema";
import { starterRegistry } from "../src/starter";

/**
 * Props the component genuinely implements and the `.strict()` node props shape
 * does not declare. Fixing these means widening `packages/schema` — routed to
 * the schema owner, deliberately not patched around here by deleting controls
 * that work.
 */
const KNOWN_GAPS: Record<string, readonly string[]> = {
  // renderer/src/nodes/layout/Container.tsx implements all six (its header
  // documents them); V2ContainerNode.props declares only `maxWidth`.
  Container: ["direction", "gap", "padding", "align", "justify", "wrap"],
  // FileUpload.schema.ts declares all five (Spec E Wave 3 resumable/retry);
  // FileUploadNode does not.
  FileUpload: ["filenameField", "mimeTypeField", "resumable", "retryOn5xx", "chunkSizeMb"],
  // RadioGroup.tsx / TimePicker.tsx both destructure `disabled` and forward it
  // to the input; neither node schema declares it.
  RadioGroup: ["disabled"],
  TimePicker: ["disabled"],
  // renderer/src/nodes/data/Repeat.tsx reads `props.bind` as an accepted alias
  // for `props.source`; V2RepeatNode documents `bind` as a TOP-LEVEL key, which
  // the properties panel — which can only ever write into `props` — cannot
  // reach. Unseeded here, so a dropped Repeat does not carry it.
  Repeat: ["bind"],
};

/**
 * Seeds whose value the node schema refuses for a reason that is the SCHEMA's to
 * relax, not the registry's to work around. Same rule as KNOWN_GAPS: named, with
 * the reason, so the entry is deleted rather than the list grown.
 */
const KNOWN_DEFAULT_GAPS: Record<string, readonly string[]> = {
  // `TabsNodePlain.props.tabs` is `.min(1)`, but Tabs now derives one tab per
  // CHILD (see the Tabs remap in packages/library/src/registry.ts) and a freshly
  // dropped Tabs legitimately has no panels yet. `[]` means "nothing declared",
  // which is under-configured, not malformed — the same distinction the menu
  // nodes were relaxed for. Seeding a tab instead would cap the strip at one
  // panel, which is the bug that remap exists to undo.
  Tabs: ["tabs"],
};

const NUMERIC_LITERAL = /^-?\d+(?:\.\d+)?$/;
/**
 * An enum whose options are numeric strings. The select control needs strings to
 * render, and `normalizeSeed` (frontend useDrop.ts) converts the seed to a real
 * number at drop time — keyed off the descriptor exactly like this, never off a
 * component name. `Heading.level: "2"` is the case; flagging it here would be
 * flagging a compensated one.
 */
function isNumericDomain(d: { type: string; options?: readonly string[] }): boolean {
  if (d.type === "number") return true;
  return d.type === "enum" && Array.isArray(d.options) && d.options.length > 0 &&
    d.options.every((o) => typeof o === "number" || (typeof o === "string" && NUMERIC_LITERAL.test(o)));
}

// Zod wrappers to walk through before asking what a schema really is.
const WRAPPERS = new Set([
  "ZodEffects", "ZodOptional", "ZodDefault", "ZodNullable", "ZodLazy",
  "ZodReadonly", "ZodBranded",
]);

function deref(schema: unknown): any {
  let d = (schema as any)?._def;
  while (d && WRAPPERS.has(d.typeName)) {
    const next = d.schema ?? d.innerType ?? (typeof d.getter === "function" ? d.getter() : null);
    d = next?._def ?? null;
  }
  return d;
}

/** Flatten NodeV2 (a union of a discriminated union and the open fallback). */
function flattenOptions(schema: unknown): unknown[] {
  const d = deref(schema);
  if (!d) return [];
  if (d.typeName === "ZodUnion") return (d.options as unknown[]).flatMap(flattenOptions);
  if (d.typeName === "ZodDiscriminatedUnion") {
    return [...((d.optionsMap?.values?.() ?? d.options ?? []) as Iterable<unknown>)];
  }
  return [schema];
}

/** type-literal → the `.strict()` props shape PageV2 will hold that node to. */
function strictPropsShapes(): Map<string, Record<string, unknown>> {
  // NodeV2 is a z.lazy; parse once so its body (and the union's optionsMap) is
  // built before anything reads it. Reading `.options` on an unresolved lazy is
  // the exact trap page.ts's own `strictTypes()` documents.
  NodeV2.safeParse({ id: "warmup", type: "Heading", props: { text: "x", level: 1 } });

  const out = new Map<string, Record<string, unknown>>();
  for (const option of flattenOptions(NodeV2)) {
    const nodeDef = deref(option);
    if (!nodeDef || nodeDef.typeName !== "ZodObject") continue;
    const nodeShape = typeof nodeDef.shape === "function" ? nodeDef.shape() : nodeDef.shape;
    const typeDef = (nodeShape?.type as any)?._def;
    if (typeDef?.typeName !== "ZodLiteral" || typeof typeDef.value !== "string") continue;
    const propsDef = deref(nodeShape.props);
    if (!propsDef || propsDef.typeName !== "ZodObject") continue;
    if (propsDef.unknownKeys !== "strict") continue; // open bridge nodes accept anything
    out.set(typeDef.value, typeof propsDef.shape === "function" ? propsDef.shape() : propsDef.shape);
  }
  return out;
}

describe("registry ↔ node-schema parity", () => {
  const shapes = strictPropsShapes();

  it("resolves the strict node shapes it is asserting against", () => {
    // Guard the guard: if NodeV2's internals move, `shapes` silently empties and
    // every assertion below passes vacuously — which is worse than no test.
    expect(shapes.size).toBeGreaterThan(70);
    expect(shapes.has("Menubar")).toBe(true);
    expect(shapes.has("Skeleton")).toBe(true);
  });

  it("declares no prop the component's strict node schema would reject", () => {
    const offenders: string[] = [];
    for (const [component, entry] of Object.entries(starterRegistry)) {
      const shape = shapes.get(component);
      if (!shape) continue;
      const allowed = KNOWN_GAPS[component] ?? [];
      for (const prop of Object.keys(entry.props)) {
        if (prop in shape) continue;
        if (allowed.includes(prop)) continue;
        offenders.push(`${component}.${prop}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("seeds no default its own prop schema refuses", () => {
    // The `""`-where-`.min(1)` class (every input's `name`, `Conditional.when`)
    // and the wrong-primitive class (`MetricTile.value` as a string) both land
    // here. `null` is exempt: it is the registry's documented "no seed" marker
    // for binding/action descriptors and `normalizeSeed` drops it at drop time.
    const offenders: string[] = [];
    for (const [component, entry] of Object.entries(starterRegistry)) {
      const shape = shapes.get(component);
      if (!shape) continue;
      for (const [prop, descriptor] of Object.entries(entry.props)) {
        if (!(prop in shape)) continue;          // covered by the test above
        if (descriptor.default === undefined) continue;
        if (descriptor.default === null) continue;
        if ((KNOWN_DEFAULT_GAPS[component] ?? []).includes(prop)) continue;
        const seed = isNumericDomain(descriptor) && typeof descriptor.default === "string" &&
          NUMERIC_LITERAL.test(descriptor.default.trim())
          ? Number(descriptor.default)
          : descriptor.default;
        const r = (shape[prop] as any).safeParse(seed);
        if (!r.success) offenders.push(`${component}.${prop} = ${JSON.stringify(descriptor.default)}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("gives every prop its node schema REQUIRES a control to fill it", () => {
    // The Menubar / ContextMenu / DropdownMenu class: a required prop with no
    // descriptor is a prop the user cannot author at all, and a node the page
    // schema will always refuse.
    const offenders: string[] = [];
    for (const [component, entry] of Object.entries(starterRegistry)) {
      const shape = shapes.get(component);
      if (!shape) continue;
      for (const [prop, propSchema] of Object.entries(shape)) {
        if ((propSchema as any).isOptional?.()) continue;
        if (prop in entry.props) continue;
        offenders.push(`${component}.${prop}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
