import { describe, it, expect } from "vitest";
import { pickResponsiveValue } from "../src/responsive/useViewport";

describe("pickResponsiveValue", () => {
  it("returns the exact-bp value", () => {
    expect(pickResponsiveValue({ default: "a", md: "b" }, "md")).toBe("b");
  });

  it("falls back to a smaller bp", () => {
    expect(pickResponsiveValue({ default: "a", md: "b" }, "lg")).toBe("b");
  });

  it("falls back to default when no smaller bp set", () => {
    expect(pickResponsiveValue({ default: "a" }, "xl")).toBe("a");
  });

  it("returns string literals unchanged", () => {
    expect(pickResponsiveValue("plain", "md")).toBe("plain");
  });

  it("returns number literals unchanged", () => {
    expect(pickResponsiveValue(42, "md")).toBe(42);
  });

  it("returns array literals unchanged", () => {
    expect(pickResponsiveValue(["a", "b"], "md")).toEqual(["a", "b"]);
  });

  it("does NOT mistake { url, overlay } for a responsive shape", () => {
    const bg = { url: "https://example.com/x.jpg", overlay: 0.4 };
    expect(pickResponsiveValue(bg, "md")).toBe(bg);
  });

  it("does NOT mistake { name, level } for a responsive shape", () => {
    const heading = { name: "h1", level: 1 };
    expect(pickResponsiveValue(heading, "md")).toBe(heading);
  });

  it("handles null + undefined", () => {
    expect(pickResponsiveValue(null as any, "md")).toBe(null);
    expect(pickResponsiveValue(undefined as any, "md")).toBe(undefined);
  });

  it("handles empty bp objects", () => {
    expect(pickResponsiveValue({}, "md")).toEqual({});
  });
});

/**
 * Regression: a breakpoint override with no base value must NEVER surface as
 * the envelope itself. Audit probe probe_props_4 rendered
 * Heading.content = {lg:"ONLYLGHEADING"} as the literal text
 * {"lg":"ONLYLGHEADING"} on every viewport under 1024px.
 */
describe("pickResponsiveValue — base-less envelopes never leak", () => {
  it("returns undefined (not the envelope) when nothing matches at or below bp", () => {
    expect(pickResponsiveValue({ lg: "ONLYLG" } as any, "default")).toBeUndefined();
    expect(pickResponsiveValue({ lg: "ONLYLG" } as any, "sm")).toBeUndefined();
    expect(pickResponsiveValue({ lg: "ONLYLG" } as any, "md")).toBeUndefined();
  });

  it("still resolves the override at and above its own breakpoint", () => {
    expect(pickResponsiveValue({ lg: "ONLYLG" } as any, "lg")).toBe("ONLYLG");
    expect(pickResponsiveValue({ lg: "ONLYLG" } as any, "xl")).toBe("ONLYLG");
  });

  it("never returns an object for any breakpoint of a bp-only envelope", () => {
    const env = { md: 3, xl: 6 } as any;
    for (const bp of ["default", "sm", "md", "lg", "xl"] as const) {
      const v = pickResponsiveValue(env, bp);
      expect(typeof v === "object" && v !== null).toBe(false);
    }
  });
});
