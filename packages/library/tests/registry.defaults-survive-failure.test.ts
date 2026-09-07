import { describe, it, expect } from "vitest";
import { z } from "zod";
import { createRegistry } from "../src/registry";
import { buildDefaultRegistry } from "../src/buildDefaultRegistry";

/**
 * THE DEFECT: one unfixable key threw away every `.default()` on the component.
 *
 * Zod applies `.default()` only as part of a SUCCESSFUL parse. `validateProps`
 * ends with "render with what we have", so whenever it could not coerce its way
 * to a passing parse, the component was handed raw props with all of its
 * declared defaults missing — because of an unrelated key.
 *
 * The audit found it through IllustratedEmpty (`title: ""` → `too_small`,
 * `action: ""` → `invalid_union`, neither with a coercion branch), and the
 * visible symptom landed on `kind`, which was never wrong. These tests are
 * written against synthetic schemas, not against IllustratedEmpty, because the
 * rule is about the mechanism: any component with one bad key must keep the
 * props that are fine.
 */

const make = (name: string, propsSchema: z.ZodTypeAny) => {
  const reg = createRegistry();
  reg.register({
    name,
    component: (() => null) as any,
    propsSchema: propsSchema as any,
    category: "display" as any,
    acceptsChildren: false,
  });
  return reg;
};

describe("validateProps keeps declared defaults when no parse succeeds", () => {
  it("restores sibling defaults when one key cannot be salvaged", () => {
    // `data` is a runtime-bound array that is legitimately short — the case the
    // step-3 comment protects, so the parse genuinely cannot be made to pass.
    const reg = make(
      "Widget",
      z.object({
        kind: z.enum(["list", "search"]).default("list"),
        density: z.string().default("cosy"),
        data: z.array(z.number()).min(2),
      }).strict(),
    );
    const out = reg.validateProps("Widget", { data: [1] });
    expect(out.data).toEqual([1]);        // preserved, not stubbed out
    expect(out.kind).toBe("list");        // WAS undefined
    expect(out.density).toBe("cosy");     // WAS undefined
  });

  it("never overwrites a value the caller actually supplied", () => {
    const reg = make(
      "Widget",
      z.object({
        kind: z.enum(["list", "search"]).default("list"),
        data: z.array(z.number()).min(2),
      }).strict(),
    );
    const out = reg.validateProps("Widget", { kind: "search", data: [1] });
    expect(out.kind).toBe("search");
  });

  it("finds defaults through .optional() and through a .superRefine wrapper", () => {
    const reg = make(
      "Widget",
      z.object({
        tone: z.string().default("neutral").optional(),
        data: z.array(z.number()).min(2),
      }).strict().superRefine(() => { /* no-op */ }),
    );
    const out = reg.validateProps("Widget", { data: [1] });
    expect(out.tone).toBe("neutral");
  });
});

describe("the three ways 'the author left this blank' arrives as a hard error", () => {
  it("`\"\"` against z.string().min(1) is read as unset, not passed through", () => {
    const reg = make(
      "Widget",
      z.object({
        title: z.string().min(1).default("Nothing here yet"),
        data: z.array(z.number()).min(2),
      }).strict(),
    );
    const out = reg.validateProps("Widget", { title: "", data: [1] });
    expect(out.title).toBe("Nothing here yet");
  });

  it("`\"\"` against a union of object shapes is dropped rather than handed over", () => {
    const reg = make(
      "Widget",
      z.object({
        action: z.union([
          z.object({ label: z.string(), workflow: z.string() }).strict(),
          z.object({ label: z.string(), navigate: z.string() }).strict(),
        ]).optional(),
        data: z.array(z.number()).min(2),
      }).strict(),
    );
    const out = reg.validateProps("Widget", { action: "", data: [1] });
    expect(out.action).toBeUndefined();
  });

  it("a typo'd enum value falls back to the enum's default instead of reaching the component", () => {
    // The UndoManager case verbatim: `POSITION_STYLES["bottom-centre"]` is
    // undefined, and the toast stack landed in the top-left corner.
    const reg = make(
      "Widget",
      z.object({
        position: z
          .enum(["bottom-left", "bottom-center", "bottom-right", "top-center"])
          .default("bottom-center"),
        data: z.array(z.number()).min(2),
      }).strict(),
    );
    const out = reg.validateProps("Widget", { position: "bottom-centre", data: [1] });
    expect(out.position).toBe("bottom-center");
  });

  it("a SHORT ARRAY is still passed through — runtime-bound data must reach the component", () => {
    const reg = make(
      "Widget",
      z.object({ data: z.array(z.number()).min(2) }).strict(),
    );
    const out = reg.validateProps("Widget", { data: [1] });
    expect(out.data).toEqual([1]);
  });
});

describe("the real component the audit found this through", () => {
  it("IllustratedEmpty with a blank title and a blank action keeps its other props", () => {
    const reg = buildDefaultRegistry();
    const out = reg.validateProps("IllustratedEmpty", {
      kind: "search",
      title: "",
      action: "",
    });
    expect(out.kind).toBe("search");
    // `title` is `.min(1)` with NO default on this component, so the honest
    // outcome is absence — not `""` masquerading as a heading.
    expect(out.title).toBeUndefined();
    expect(out.action).toBeUndefined();
  });
});
