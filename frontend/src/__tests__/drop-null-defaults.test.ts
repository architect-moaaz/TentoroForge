/**
 * A dropped node must never carry a `null` prop.
 *
 * The registry's descriptor convention for "no seed" on binding/action props is
 * `default: null`. `defaultPropsFor` filtered only `undefined`, so those nulls
 * were copied verbatim onto every new node — and then persisted. Component
 * schemas type those props `z.string().optional()`, and `null` is not
 * `undefined`, so the whole props parse failed and every Zod `.default()` on
 * the component was silently skipped (see registry.null-binding.test.ts in
 * @tentoroforge/library for the other half of this fix).
 */
import { describe, it, expect } from "vitest";
import { starterRegistry } from "@forge/registry";
import { defaultPropsFor, normalizeSeed } from "../components/canvas/hooks/useDrop";

describe("defaultPropsFor: null seeds", () => {
  it("normalizeSeed omits a null default", () => {
    expect(normalizeSeed({ type: "binding", control: "binding" }, null)).toBeUndefined();
    expect(normalizeSeed({ type: "string", control: "text" }, null)).toBeUndefined();
    // Real values still pass through untouched.
    expect(normalizeSeed({ type: "string", control: "text" }, "hi")).toBe("hi");
    expect(normalizeSeed({ type: "boolean", control: "toggle" }, false)).toBe(false);
    expect(normalizeSeed({ type: "number", control: "number" }, 0)).toBe(0);
  });

  it("emits no null-valued prop for ANY starter registry component", () => {
    const names = Object.keys(starterRegistry as Record<string, unknown>);
    expect(names.length).toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const name of names) {
      for (const [prop, value] of Object.entries(defaultPropsFor(name))) {
        if (value === null) offenders.push(`${name}.${prop}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("still seeds the props that DO have a real default", () => {
    // At least one entry in the catalog must survive the filter, otherwise the
    // assertion above would pass vacuously.
    const names = Object.keys(starterRegistry as Record<string, unknown>);
    const seeded = names.filter((n) => Object.keys(defaultPropsFor(n)).length > 0);
    expect(seeded.length).toBeGreaterThan(0);
  });
});
