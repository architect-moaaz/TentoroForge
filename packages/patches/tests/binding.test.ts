import { describe, it, expect } from "vitest";
import {
  isBinding, isMustacheBinding, isLegacyBinding,
  bindingExpression, toBindingValue, migrateBindingsDeep,
} from "../src/binding";
import { validateNoLegacyBindings, validateForCommit } from "../src/validate";
import type { Artifacts } from "../src/types";

/**
 * The editor's Bindings tab used to write `{ $binding: "expr" }` — a shape no
 * renderer, engine, library or schema package has ever implemented. It passed
 * every gate silently and surfaced only as a rendered "⚠ render error", by
 * which point autosave had already written it into the page schema and the
 * generated app. These tests pin the replacement and the escape routes.
 */

const page = (props: Record<string, unknown>): Artifacts => ({
  pageSchemas: {
    home: {
      id: "home", route: "/", schemaVersion: "2",
      root: { id: "root", type: "Container", children: [{ id: "btn", type: "Button", props }] },
    } as never,
  },
  navFlow: { pages: [{ id: "home", route: "/" }] } as never,
  tokens: {} as never,
});

describe("binding format predicates", () => {
  it("recognises the mustache string form", () => {
    expect(isMustacheBinding("{{user.name}}")).toBe(true);
    expect(isMustacheBinding("Hi {{user.name}}!")).toBe(true);
    expect(isMustacheBinding("plain")).toBe(false);
    expect(isMustacheBinding({ $binding: "x" })).toBe(false);
  });

  it("still recognises the legacy object so un-migrated pages display correctly", () => {
    expect(isLegacyBinding({ $binding: "user.name" })).toBe(true);
    // Key PRESENCE, not truthiness — a toggled-but-unfilled bind must still read
    // as bound, or the panel hides it and the user cannot unbind it.
    expect(isLegacyBinding({ $binding: "" })).toBe(true);
    expect(isLegacyBinding([])).toBe(false);
    expect(isLegacyBinding(null)).toBe(false);
  });

  it("extracts the same expression from either form", () => {
    expect(bindingExpression("{{ user.name }}")).toBe("user.name");
    expect(bindingExpression({ $binding: "user.name" })).toBe("user.name");
    expect(isBinding("{{a}}") && isBinding({ $binding: "a" })).toBe(true);
  });

  it("wraps an expression, but never produces the empty template \"{{}}\"", () => {
    expect(toBindingValue("user.name")).toBe("{{user.name}}");
    expect(toBindingValue("  spaced  ")).toBe("{{spaced}}");
    expect(toBindingValue("")).toBe("");
    expect(toBindingValue("   ")).toBe("");
  });
});

describe("migrateBindingsDeep", () => {
  it("converts a legacy object to the string the renderer resolves", () => {
    expect(migrateBindingsDeep({ label: { $binding: "items[0].name" } }))
      .toEqual({ label: "{{items[0].name}}" });
  });

  it("reaches into the responsive breakpoint envelope and into arrays", () => {
    // A bound prop can sit inside {default, lg} or any nested structure, so a
    // shallow pass would leave the object exactly where it still breaks React.
    expect(migrateBindingsDeep({ w: { default: { $binding: "a" }, lg: "8rem" } }))
      .toEqual({ w: { default: "{{a}}", lg: "8rem" } });
    expect(migrateBindingsDeep({ cols: [{ label: { $binding: "c.name" } }] }))
      .toEqual({ cols: [{ label: "{{c.name}}" }] });
  });

  it("returns the SAME object when there is nothing to migrate", () => {
    // Identity is the cheap path: every page load runs this, and the
    // overwhelming majority of props have no legacy binding in them.
    const clean = { label: "Save", style: { width: "100%" } };
    expect(migrateBindingsDeep(clean)).toBe(clean);
  });

  it("leaves mustache strings and ordinary values untouched", () => {
    expect(migrateBindingsDeep({ a: "{{x}}", b: 3, c: null, d: false }))
      .toEqual({ a: "{{x}}", b: 3, c: null, d: false });
  });
});

describe("validateNoLegacyBindings", () => {
  it("rejects the legacy object and names the prop and its replacement", () => {
    const errs = validateNoLegacyBindings(page({ label: { $binding: "items[0].name" } }));
    expect(errs).toHaveLength(1);
    expect(errs[0]).toContain("btn");
    expect(errs[0]).toContain("label");
    expect(errs[0]).toContain("{{items[0].name}}");
  });

  it("finds one nested inside a breakpoint envelope", () => {
    const errs = validateNoLegacyBindings(page({ style: { default: { $binding: "w" } } }));
    expect(errs).toHaveLength(1);
    expect(errs[0]).toContain("style.default");
  });

  it("passes the format that actually works", () => {
    expect(validateNoLegacyBindings(page({ label: "{{items[0].name}}" }))).toEqual([]);
  });

  it("runs at the commit boundary, which is where the old bug walked through", () => {
    expect(validateForCommit(page({ label: { $binding: "x" } })).length).toBeGreaterThan(0);
    expect(validateForCommit(page({ label: "{{x}}" }))).toEqual([]);
  });
});
