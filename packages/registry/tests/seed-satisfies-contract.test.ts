/**
 * A REGISTRY SEED MUST BE A VALUE THE COMPONENT'S OWN SCHEMA ACCEPTS.
 *
 * `node-schema-parity.test.ts` guards the registry against `packages/schema`'s
 * `.strict()` NODE shapes. This guards it against the other contract — the
 * component's own zod props schema in `packages/library`, the one
 * `validateProps` actually runs at render time. They are different documents
 * and they drift independently, which is how this got through:
 *
 *   `tourOverlayEntry.steps` was `{ type: "string", control: "text",
 *   default: "" }` against `TourOverlayProps.steps = z.array(TourStep).min(1)`
 *   — required, no default. Building the entry's own default props object and
 *   parsing it FAILED with "expected array, received string". `TourOverlay.tsx`
 *   then does `Array.isArray(steps) ? … : []` and returns null, so every
 *   palette-dropped TourOverlay was invalid on arrival and rendered a 0x0 node
 *   with no hint. There was no node schema to catch it either — TourOverlay
 *   validates only through `page.ts`'s `anyRegistered` fallback, whose props are
 *   `z.record(z.unknown())` — so nothing anywhere said no.
 *
 * It is the same class as `Select.options` and `Wizard.steps`, both already
 * fixed one instance at a time. This is the alarm, so the fourth instance is a
 * failing test rather than a fifth audit round.
 *
 * WHY IT READS A BUILD ARTEFACT
 * -----------------------------
 * `packages/registry` depends on zod and nothing else — deliberately, since the
 * editor loads it. It cannot import `packages/library` to reach the zod schemas,
 * and making it able to would invert the dependency the whole package exists to
 * avoid. `dist/component-contracts.json` is exactly this seam and already
 * exists: `scripts/extract-contracts.ts` reduces every live library schema to
 * `{ type, enum?, optional? }` for the page composer's prompt, sourced from the
 * schemas so it cannot drift from what the renderer accepts.
 *
 * The artefact is a build output and is gitignored, so the suite SKIPS rather
 * than fails when it is absent — `npm run build` in this package writes it, and
 * that is the order CI runs in. A skip says "not checked"; a failure here would
 * say "the registry is wrong", which would be a lie on a clean checkout.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { starterRegistry } from "../src/starter";

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONTRACTS = resolve(__dirname, "..", "dist", "component-contracts.json");

type Contract = Record<string, { type: string; enum?: unknown[]; optional?: boolean }>;

const contracts: Record<string, Contract> | null = existsSync(CONTRACTS)
  ? JSON.parse(readFileSync(CONTRACTS, "utf-8"))
  : null;

/**
 * The drop path's own seed normalisation, replicated.
 *
 * A seed is NOT written to the node verbatim: `normalizeSeed`
 * (frontend/src/components/canvas/hooks/useDrop.ts) coerces it first, and this
 * check has to compare what the component will actually receive or it reports
 * fixes as failures. Specifically `Heading.level` is a `type: "enum"` over
 * `["1".."6"]` seeded `"2"` against `z.number()` — the `<select>` control needs
 * string options, and the drop path turns the chosen string back into a number.
 * Comparing the raw seed would flag that deliberate, already-fixed arrangement.
 *
 * Replicated rather than imported because `packages/registry` depends on zod
 * and nothing else — it cannot reach into `frontend`, and inverting that is
 * exactly what the package is shaped to avoid. Both rules key off the
 * DESCRIPTOR, never off a component name, so they stay in step by construction;
 * if they ever do drift, this guard gets louder, not quieter.
 */
const NUMERIC_LITERAL = /^-?\d+(?:\.\d+)?$/;

function isNumericDomain(d: any): boolean {
  if (d?.type === "number") return true;
  return (
    d?.type === "enum" &&
    Array.isArray(d.options) &&
    d.options.length > 0 &&
    d.options.every((o: unknown) => typeof o === "number" || (typeof o === "string" && NUMERIC_LITERAL.test(o)))
  );
}

function normalizeSeed(d: any, value: unknown): unknown {
  if (value === undefined || value === null) return undefined;
  if (isNumericDomain(d) && typeof value === "string" && NUMERIC_LITERAL.test(value.trim())) {
    return Number(value);
  }
  if (d?.control === "image" && d?.imageShape === "url" && value === "") return undefined;
  return value;
}

/** The props object a palette drop actually starts from. */
function seededProps(entry: { props: Record<string, { default?: unknown }> }): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, d] of Object.entries(entry.props)) {
    // `null` is the registry's documented "no seed" marker for binding and
    // action descriptors; `normalizeSeed` strips it at drop, so it never
    // reaches the component and must not be checked as though it did.
    const v = normalizeSeed(d, (d as any).default);
    if (v !== undefined) out[k] = v;
  }
  return out;
}

/**
 * Required contract props that are deliberately left UNSEEDED, with the reason.
 *
 * "Required with no seed" is not automatically a bug — it is a bug only when
 * the author cannot then reach the prop, or when the component renders nothing
 * without it (TourOverlay, which is why this file exists). For these three the
 * component renders fine and the value is genuinely the author's to supply, and
 * seeding them was itself the previous bug: every input seeded `name: ""`
 * against a `z.string().min(1)`, so every dropped input was invalid on arrival.
 * The empty string was removed on purpose; do not "fix" these by putting it
 * back. A NEW name appearing here is a new bug.
 */
const DELIBERATELY_UNSEEDED = new Set([
  // Removed by the `21 input name seeds` class fix: `""` fails `.min(1)`, and a
  // form control's name is the author's, not a default anyone can guess.
  "Textarea.name",
  "Select.name",
  // A redirect with an invented destination is worse than one that is visibly
  // unconfigured — a seeded route would silently send users somewhere.
  "Redirect.to",
]);

/** The contract's `type` vocabulary, as a predicate over a real seed value. */
function matchesContractType(value: unknown, type: string): boolean {
  switch (type) {
    case "array":   return Array.isArray(value);
    case "object":  return typeof value === "object" && value !== null && !Array.isArray(value);
    case "string":  return typeof value === "string";
    case "number":  return typeof value === "number";
    case "boolean": return typeof value === "boolean";
    case "enum":    return true;   // membership is checked separately, below
    // "any"/"unknown" accept anything by construction, and an unrecognised type
    // is not this test's business to reject.
    default:        return true;
  }
}

describe("every registry seed is a value the component's own schema accepts", () => {
  it.skipIf(!contracts)("no seed contradicts its contract's declared type", () => {
    const bad: string[] = [];
    for (const entry of Object.values(starterRegistry)) {
      const contract = contracts?.[entry.name];
      if (!contract) continue;             // no library schema for this type
      for (const [prop, value] of Object.entries(seededProps(entry))) {
        const c = contract[prop];
        if (!c) continue;                  // prop not in the contract: parity test's job
        if (!matchesContractType(value, c.type)) {
          bad.push(`${entry.name}.${prop}: seed is ${Array.isArray(value) ? "array" : typeof value}, contract says ${c.type}`);
        }
        if (c.type === "enum" && Array.isArray(c.enum) && !c.enum.includes(value as never)) {
          bad.push(`${entry.name}.${prop}: seed ${JSON.stringify(value)} is not one of ${JSON.stringify(c.enum)}`);
        }
      }
    }
    expect(bad).toEqual([]);
  });

  it.skipIf(!contracts)("no REQUIRED contract prop is left unseeded", () => {
    // The other half of the TourOverlay failure: `steps` is required with no
    // default, so a drop that does not seed it is invalid before the author
    // touches anything. A required prop the registry cannot fill is a component
    // nobody can drop.
    const missing: string[] = [];
    for (const entry of Object.values(starterRegistry)) {
      const contract = contracts?.[entry.name];
      if (!contract) continue;
      const seeded = seededProps(entry);
      for (const [prop, c] of Object.entries(contract)) {
        if (c.optional) continue;
        // `children` is supplied by the slot machinery, not by a prop seed.
        if (prop === "children") continue;
        if (DELIBERATELY_UNSEEDED.has(`${entry.name}.${prop}`)) continue;
        if (!(prop in seeded)) missing.push(`${entry.name}.${prop} (contract: required ${c.type})`);
      }
    }
    expect(missing).toEqual([]);
  });

  it.skipIf(!contracts)("TourOverlay — the instance that produced this guard", () => {
    const entry = Object.values(starterRegistry).find((e) => e.name === "TourOverlay")!;
    const steps = entry.props.steps;
    expect(steps.type).toBe("array");
    expect(steps.control).toBe("json");
    expect(Array.isArray(steps.default)).toBe(true);
    // `.min(1)` — an empty array is as invalid as the empty string was.
    expect((steps.default as unknown[]).length).toBeGreaterThan(0);
    expect(contracts?.TourOverlay?.steps).toMatchObject({ type: "array" });
  });
});

describe("TableSortable's void", () => {
  it("offers a route to a row", () => {
    // The component built its <tbody> from `children` alone while this entry
    // declares it a leaf, so every route to a row was closed and a dropped
    // TableSortable was a header over nothing, permanently.
    const entry = Object.values(starterRegistry).find((e) => e.name === "TableSortable")!;
    expect("rows" in entry.props).toBe(true);
    expect(entry.props.rows.control).toBe("binding");
    // A binding, not a seeded literal array: a sample array here would freeze
    // design-time data into a shipped app.
    expect(entry.props.rows.default).toBeNull();
  });

  it("offers no onSort control, because the only value one could write is a crash", () => {
    // The component CALLS onSort(key, dir), so a JSON control could only ever
    // put a truthy non-function there and the next header click throws
    // "onSort is not a function". It was inert only for as long as nobody used
    // the control the editor offered.
    const entry = Object.values(starterRegistry).find((e) => e.name === "TableSortable")!;
    expect("onSort" in entry.props).toBe(false);
  });
});
