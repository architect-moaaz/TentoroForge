import { describe, it, expect } from "vitest";
import { z } from "zod";
import { createRegistry } from "../src/registry";
import { buildDefaultRegistry } from "../src/buildDefaultRegistry";

/**
 * Regression: `bind: null` silently disabled the ENTIRE props validation.
 *
 * The registry's descriptor convention is `{ type: "binding", default: null }`,
 * which `defaultPropsFor` copied verbatim onto every dropped node — and those
 * `bind: null` values are persisted in project schemas already on disk. Every
 * component schema types the prop `z.string().optional()`, and `null` is not
 * `undefined`, so the parse failed; step 3's coercion table had no branch for
 * `received: "null"`, so the final parse failed too and `validateProps`
 * returned the RAW props. Consequence: every Zod `.default()` on that
 * component was skipped and it rendered as if it had no props at all.
 */
describe("validateProps: null on a non-nullable optional field", () => {
  function makeRegistry() {
    const r = createRegistry();
    r.register({
      name: "Widget",
      component: (() => null) as any,
      // The real shape: an optional binding + several props carrying defaults.
      propsSchema: z.object({
        bind: z.string().optional(),
        onSelect: z.string().optional(),
        max: z.number().default(100),
        variant: z.enum(["a", "b"]).default("a"),
        showLabel: z.boolean().default(true),
      }),
      category: "display" as any,
      acceptsChildren: false,
    });
    return r;
  }

  it("applies the schema defaults instead of returning the raw props", () => {
    const out = makeRegistry().validateProps("Widget", { bind: null });
    // The heart of the bug: before the fix these three were all absent.
    expect(out.max).toBe(100);
    expect(out.variant).toBe("a");
    expect(out.showLabel).toBe(true);
    // The offending null is dropped, not carried through as `null`.
    expect(out.bind).toBeUndefined();
    expect("bind" in out).toBe(false);
  });

  it("drops several null bindings at once and keeps real values", () => {
    const out = makeRegistry().validateProps("Widget", {
      bind: null,
      onSelect: null,
      max: 7,
    });
    expect(out.max).toBe(7);
    expect(out.variant).toBe("a");
    expect(out.bind).toBeUndefined();
    expect(out.onSelect).toBeUndefined();
  });

  it("PRESERVES null on a field the schema declares nullable", () => {
    const r = createRegistry();
    r.register({
      name: "Nullable",
      component: (() => null) as any,
      propsSchema: z.object({
        value: z.string().nullable(),
        other: z.string().optional(),
        size: z.number().default(4),
      }),
      category: "display" as any,
      acceptsChildren: false,
    });
    const out = r.validateProps("Nullable", { value: null, other: null });
    expect(out.value).toBeNull();      // genuinely nullable — untouched
    expect(out.other).toBeUndefined(); // optional, not nullable — dropped
    expect(out.size).toBe(4);
  });

  it("falls back to an empty value when the nulled field is REQUIRED", () => {
    const r = createRegistry();
    r.register({
      name: "Required",
      component: (() => null) as any,
      propsSchema: z.object({
        label: z.string(),
        tone: z.string().default("neutral"),
      }),
      category: "display" as any,
      acceptsChildren: false,
    });
    const out = r.validateProps("Required", { label: null });
    expect(out.label).toBe("");
    expect(out.tone).toBe("neutral");
  });

  it("handles a null nested inside an object prop", () => {
    const r = createRegistry();
    r.register({
      name: "Nested",
      component: (() => null) as any,
      propsSchema: z.object({
        cfg: z.object({
          bind: z.string().optional(),
          step: z.number().default(2),
        }),
      }),
      category: "display" as any,
      acceptsChildren: false,
    });
    const out = r.validateProps("Nested", { cfg: { bind: null } });
    expect((out.cfg as any).step).toBe(2);
    expect((out.cfg as any).bind).toBeUndefined();
  });

  it("never throws on a null for any real registry entry", () => {
    const reg = buildDefaultRegistry();
    for (const entry of reg.list()) {
      expect(() => reg.validateProps(entry.name, { bind: null })).not.toThrow();
    }
  });
});
