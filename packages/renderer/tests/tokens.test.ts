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
