/**
 * The library keeps its own copy of the StyleSlot resolution (the renderer's
 * runtime/style-slot.ts is the other one — deliberately duplicated to keep the
 * two packages free of a circular dependency). These tests exist because the
 * copies MUST agree: a background painted one way by a structural Box and
 * another by a library Card is worse than either behaviour alone.
 *
 * The bug being locked out: any string background was token-wrapped, so
 * "#3b82f6" became `var(--token-#3b82f6)` and the fill silently never painted.
 */
import { describe, it, expect } from "vitest";
import { resolveStyle, resolveStyleNoBackground } from "../src/style/resolveStyle";

describe("resolveStyle background — token vs raw", () => {
  it("compiles token refs, with or without the tokens. prefix", () => {
    expect(resolveStyle({ background: "color.primary.500" } as never).background)
      .toBe("var(--token-color-primary-500)");
    expect(resolveStyle({ background: "tokens.color.surface.0" } as never).background)
      .toBe("var(--token-color-surface-0)");
  });

  it("passes raw CSS fills through verbatim", () => {
    for (const raw of [
      "#3b82f6",
      "rebeccapurple",
      "rgb(59 130 246)",
      "hsl(230 30% 10% / 0.62)",
      "linear-gradient(to bottom, white, black)",
      "transparent",
    ]) {
      expect(resolveStyle({ background: raw } as never).background).toBe(raw);
    }
  });

  it("applies the same rule inside the structured solid/gradient forms", () => {
    expect(resolveStyle({ background: { type: "solid", value: "#3b82f6" } } as never).background)
      .toBe("#3b82f6");
    expect(resolveStyle({
      background: { type: "gradient", from: "#000000", to: "color.accent.500", angle: 90 },
    } as never).background)
      .toBe("linear-gradient(90deg, #000000 0%, var(--token-color-accent-500) 100%)");
  });
});

describe("resolveStyle motion duration", () => {
  const dur = (s: unknown) => (resolveStyle(s as never) as Record<string, string>)["--motion-duration"];

  it("emits --motion-duration when a motion is set", () => {
    expect(dur({ motion: "slide-in", motionDuration: "1s" })).toBe("1s");
  });

  it("emits nothing without a motion, or with motion:none", () => {
    expect(dur({ motionDuration: "1s" })).toBeUndefined();
    expect(dur({ motion: "none", motionDuration: "1s" })).toBeUndefined();
    expect(dur({ motion: "fade-up" })).toBeUndefined();
  });

  it("still emits on the no-background variant — that element carries data-motion too", () => {
    const out = resolveStyleNoBackground({ motion: "stagger", motionDuration: "250ms" } as never);
    expect((out as Record<string, string>)["--motion-duration"]).toBe("250ms");
    expect(out.background).toBeUndefined();
  });
});

// Scale keys use the OTHER rule: a bare word there is a token ("md"), not a
// literal. Getting this backwards would silently drop every `"padding": "md"`
// in the existing schemas.
describe("resolveStyle scale keys — token refs vs raw CSS", () => {
  it("wraps bare scale names and dotted paths alike", () => {
    const out = resolveStyle({ padding: "md", radius: "radius.lg", shadow: "sm" } as never);
    expect(out.padding).toBe("var(--token-md)");
    expect(out.borderRadius).toBe("var(--token-radius-lg)");
    expect(out.boxShadow).toBe("var(--token-sm)");
  });

  it("passes raw lengths, keywords and literal shadows through", () => {
    const out = resolveStyle({
      padding: "1rem",
      radius: "0",
      shadow: "0 1px 2px rgb(0 0 0 / 0.05)",
    } as never);
    expect(out.padding).toBe("1rem");
    expect(out.borderRadius).toBe("0");
    expect(out.boxShadow).toBe("0 1px 2px rgb(0 0 0 / 0.05)");
  });

  it("emits no var() containing a '#' or '(' — the shape of the original bug", () => {
    const out = resolveStyle({
      background: "#945151", padding: "1rem", shadow: "0 1px 2px rgb(0 0 0 / 0.05)",
    } as never);
    for (const v of Object.values(out)) {
      expect(String(v)).not.toMatch(/var\(--token-[^)]*[#(][^)]*\)/);
    }
  });
});
