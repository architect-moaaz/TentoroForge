import { describe, it, expect } from "vitest";
import { tokenToCssVar, compileTokens, resolveStyle } from "../src/runtime/tokens";

const theme = {
  colors: { "primary.500": "#3b82f6", "neutral.900": "#0b0b0c" },
  spacing: { "spacing.4": "1rem", "spacing.6": "1.5rem" },
};

describe("tokenToCssVar", () => {
  it("maps a dotted token to a CSS variable name", () => {
    expect(tokenToCssVar("primary.500")).toBe("--token-primary-500");
  });
});

describe("compileTokens", () => {
  it("produces a flat record of CSS-var → value", () => {
    const out = compileTokens(theme);
    expect(out["--token-primary-500"]).toBe("#3b82f6");
    expect(out["--token-spacing-4"]).toBe("1rem");
  });
});

describe("resolveStyle", () => {
  it("converts StyleProps token refs to CSS values", () => {
    const out = resolveStyle({ color: "primary.500", padding: "spacing.4" });
    expect(out.color).toBe("var(--token-primary-500)");
    expect(out.padding).toBe("var(--token-spacing-4)");
  });
});

/**
 * resolveStyle used to wrap EVERY string value, so a raw value on any mapped
 * key became an invalid custom property. Live proof from project gh0mlpbp:
 * node container-2hmhdg has `background: "#945151"` and rendered as
 *   style="…;background-color:var(--token-#945151);background:#945151"
 * — the hex painted only because applyStyleSlot's `background` SHORTHAND is
 * spread after this and reset `background-color`. `color` and `borderColor`
 * get no such shorthand, so a raw colour on those was broken outright.
 *
 * These tests exist because unit tests on applyStyleSlot alone did NOT catch
 * that: the defect lived in a sibling function composed onto the same element.
 */
describe("resolveStyle — token refs vs raw CSS values", () => {
  it("still wraps genuine token refs", () => {
    const out = resolveStyle({
      color: "color.text.primary",
      background: "color.primary.500",
      borderColor: "color.border.default",
      padding: "spacing.4",
      gap: "md",          // bare scale name — resolves via compileTokens' alias
      width: "sizes.full",
    } as never);
    expect(out.color).toBe("var(--token-color-text-primary)");
    expect(out.backgroundColor).toBe("var(--token-color-primary-500)");
    expect(out.borderColor).toBe("var(--token-color-border-default)");
    expect(out.padding).toBe("var(--token-spacing-4)");
    expect(out.gap).toBe("var(--token-md)");
    expect(out.width).toBe("var(--token-sizes-full)");
  });

  it("passes raw colours through on every colour key", () => {
    const out = resolveStyle({
      background: "#945151",
      color: "rebeccapurple",
      borderColor: "rgb(59 130 246)",
    } as never);
    expect(out.backgroundColor).toBe("#945151");
    expect(out.color).toBe("rebeccapurple");
    expect(out.borderColor).toBe("rgb(59 130 246)");
  });

  it("passes raw sizes, type scales and keywords through", () => {
    const out = resolveStyle({
      width: "788px",
      height: "50%",
      lineHeight: "1.5",
      letterSpacing: "-0.01em",
      fontWeight: "bold",
      borderRadius: "0",
      shadow: "0 1px 2px rgb(0 0 0 / 0.05)",
    } as never);
    expect(out.width).toBe("788px");
    expect(out.height).toBe("50%");
    expect(out.lineHeight).toBe("1.5");
    expect(out.letterSpacing).toBe("-0.01em");
    expect(out.fontWeight).toBe("bold");
    expect(out.borderRadius).toBe("0");
    expect(out.boxShadow).toBe("0 1px 2px rgb(0 0 0 / 0.05)");
  });

  it("emits no var() containing a '#' or '(' — the exact shape of the bug", () => {
    const out = resolveStyle({
      background: "#945151",
      color: "hsl(210 20% 98%)",
      width: "788px",
    } as never);
    for (const v of Object.values(out)) {
      expect(String(v)).not.toMatch(/var\(--token-[^)]*[#(][^)]*\)/);
    }
  });
});
