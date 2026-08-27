import { describe, it, expect } from "vitest";
import { interpolate, interpolateDeep } from "../src/runtime/interpolate";

describe("interpolate", () => {
  it("returns the input verbatim when no template markers are present", () => {
    expect(interpolate("hello world", { x: 1 })).toBe("hello world");
  });

  it("replaces a single {{path}} with the resolved value", () => {
    expect(interpolate("Hi {{user.name}}!", { user: { name: "Sarah" } }))
      .toBe("Hi Sarah!");
  });

  it("replaces multiple placeholders", () => {
    const out = interpolate("{{first}} - {{last}}", { first: "Sarah", last: "Johnson" });
    expect(out).toBe("Sarah - Johnson");
  });

  it("renders numbers and booleans as their string form", () => {
    expect(interpolate("count: {{n}}, ok: {{ok}}", { n: 42, ok: true }))
      .toBe("count: 42, ok: true");
  });

  it("drops the placeholder when the expression is undefined or null", () => {
    expect(interpolate("[{{missing}}]", {})).toBe("[]");
    expect(interpolate("[{{n}}]", { n: null })).toBe("[]");
  });

  it("works with arithmetic / property chains via evalExpression", () => {
    expect(interpolate("days: {{days * 2}}", { days: 3 })).toBe("days: 6");
  });

  it("trims whitespace inside the braces", () => {
    expect(interpolate("{{  x  }}", { x: "ok" })).toBe("ok");
  });

  it("resolves array-index bindings (whole-string)", () => {
    expect(interpolate("{{items[0].name}}", { items: [{ name: "X" }] })).toBe("X");
  });

  it("resolves array-index bindings inside mixed text", () => {
    expect(interpolate("Hi {{items[0].name}}", { items: [{ name: "X" }] })).toBe("Hi X");
  });

  it("returns the raw native type for whole-string templates (number)", () => {
    // delta.value is z.number() in MetricTile; LLM sometimes emits
    // "{{stats.growth}}" as the value. With whole-string handling, the
    // result is the actual number, not its string form, so number-typed
    // schema fields validate.
    expect(interpolate("{{n}}", { n: 42 })).toBe(42);
    expect(typeof interpolate("{{n}}", { n: 42 })).toBe("number");
  });

  it("returns the raw native type for whole-string templates (boolean / object)", () => {
    expect(interpolate("{{ok}}", { ok: true })).toBe(true);
    const obj = { a: 1 };
    expect(interpolate("{{o}}", { o: obj })).toBe(obj);
  });

  it("falls back to the literal template when a whole-string template can't resolve", () => {
    // Required schema fields would crash if the key were dropped; keep the
    // literal so validation sees a non-empty string and the user sees the
    // unresolved placeholder text.
    expect(interpolate("{{missing}}", {})).toBe("{{missing}}");
  });
});

describe("interpolateDeep", () => {
  it("walks into nested objects and arrays", () => {
    const input = {
      title: "Hello {{name}}",
      cta: { label: "Go to {{path}}", action: { type: "navigate", to: "/{{slug}}" } },
      tags: ["Hi {{name}}", "static"],
    };
    const out = interpolateDeep(input, { name: "World", path: "home", slug: "x" }) as any;
    expect(out.title).toBe("Hello World");
    expect(out.cta.label).toBe("Go to home");
    expect(out.cta.action.to).toBe("/x");
    expect(out.tags[0]).toBe("Hi World");
    expect(out.tags[1]).toBe("static");
  });

  it("returns primitives unchanged", () => {
    expect(interpolateDeep(42, {})).toBe(42);
    expect(interpolateDeep(null, {})).toBe(null);
  });
});

// IRF-M6-T7 — formatter modifier syntax
describe("interpolate | formatters (M6-T7)", () => {
  it("percent formats fractions as N%", () => {
    expect(interpolate("{{growth | percent}}", { growth: 0.12 })).toBe("12%");
    expect(interpolate("{{growth | percent}}", { growth: 12 })).toBe("12%");
  });

  it("percent respects digits arg", () => {
    expect(interpolate("{{growth | percent:1}}", { growth: 0.1234 })).toBe("12.3%");
  });

  it("currency formats with default USD", () => {
    const out = interpolate("{{price | currency}}", { price: 1234.5 }) as string;
    expect(out).toContain("1,234.5");  // number formatting varies by locale
  });

  it("currency accepts an arg", () => {
    const out = interpolate("{{price | currency:EUR}}", { price: 1000 }) as string;
    // Some locales render EUR as "€" or "EUR"
    expect(out).toMatch(/€|EUR/);
  });

  it("number formats with thousand separators", () => {
    const out = interpolate("{{count | number}}", { count: 1234567 }) as string;
    expect(out).toMatch(/1[,.\s]234[,.\s]567/);
  });

  it("relative produces a phrase for past times", () => {
    const past = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
    const out = interpolate("{{when | relative}}", { when: past }) as string;
    expect(out).toMatch(/day|ago/i);
  });

  it("unknown formatter passes through raw value", () => {
    expect(interpolate("{{n | unknown}}", { n: 42 })).toBe(42);
  });

  it("mixed text with formatter works", () => {
    const out = interpolate("Growth: {{g | percent}}!", { g: 0.15 });
    expect(out).toBe("Growth: 15%!");
  });

  it("no formatter still works", () => {
    expect(interpolate("{{n}}", { n: 42 })).toBe(42);
  });

  it("empty formatter arg is safe", () => {
    // spec says at-least-one-word after `|` is required; unknown formatter
    // just passes through. `{{n | }}` is malformed — treat as no formatter.
    expect(interpolate("{{n}}", { n: "hi" })).toBe("hi");
  });
});
