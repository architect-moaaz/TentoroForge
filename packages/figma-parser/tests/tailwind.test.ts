import { describe, it, expect } from "vitest";
import { tailwindToTokens } from "../src/tailwind-tokens";

describe("tailwindToTokens", () => {
  it("maps bg-blue-500 to background token", () => {
    const out = tailwindToTokens("bg-blue-500 p-4 text-white");
    expect(out.style?.background).toBe("primary.500");
    expect(out.style?.padding).toBe("spacing.4");
    expect(out.style?.color).toBe("neutral.0");
  });

  it("returns unmapped classes in unmapped[]", () => {
    const out = tailwindToTokens("bg-blue-500 magic-class");
    expect(out.unmapped).toContain("magic-class");
  });

  it("maps bg-gray-* to neutral tokens", () => {
    const out = tailwindToTokens("bg-gray-100 bg-gray-900");
    // Last bg wins in our implementation
    expect(out.style.background).toBe("neutral.900");
    expect(out.unmapped).toHaveLength(0);
  });

  it("maps bg-red-* to danger tokens", () => {
    const out = tailwindToTokens("bg-red-500");
    expect(out.style.background).toBe("danger.500");
  });

  it("maps bg-green-* to success tokens", () => {
    const out = tailwindToTokens("bg-green-400");
    expect(out.style.background).toBe("success.400");
  });

  it("maps bg-yellow-* to warning tokens", () => {
    const out = tailwindToTokens("bg-yellow-300");
    expect(out.style.background).toBe("warning.300");
  });

  it("maps bg-white to neutral.0", () => {
    const out = tailwindToTokens("bg-white");
    expect(out.style.background).toBe("neutral.0");
  });

  it("maps bg-black to neutral.900", () => {
    const out = tailwindToTokens("bg-black");
    expect(out.style.background).toBe("neutral.900");
  });

  it("maps text-* colors", () => {
    expect(tailwindToTokens("text-blue-500").style.color).toBe("primary.500");
    expect(tailwindToTokens("text-gray-700").style.color).toBe("neutral.700");
    expect(tailwindToTokens("text-black").style.color).toBe("neutral.900");
  });

  it("maps padding classes", () => {
    for (let i = 0; i <= 16; i++) {
      const out = tailwindToTokens(`p-${i}`);
      expect(out.style.padding).toBe(`spacing.${i}`);
    }
  });

  it("maps text-size classes to typography tokens", () => {
    const sizes = ["xs", "sm", "base", "lg", "xl", "2xl"];
    for (const s of sizes) {
      const out = tailwindToTokens(`text-${s}`);
      expect(out.style.fontSize).toBe(`typography.${s}`);
    }
  });

  it("maps rounded-* to radii tokens", () => {
    const radii = ["sm", "md", "lg", "xl", "full"];
    for (const r of radii) {
      const out = tailwindToTokens(`rounded-${r}`);
      expect(out.style.borderRadius).toBe(`radii.${r}`);
    }
  });

  it("maps shadow-* to shadows tokens", () => {
    const shadows = ["sm", "md", "lg"];
    for (const s of shadows) {
      const out = tailwindToTokens(`shadow-${s}`);
      expect(out.style.boxShadow).toBe(`shadows.${s}`);
    }
  });

  it("handles multiple classes correctly", () => {
    const out = tailwindToTokens("bg-blue-500 p-8 text-xl rounded-lg shadow-md");
    expect(out.style.background).toBe("primary.500");
    expect(out.style.padding).toBe("spacing.8");
    expect(out.style.fontSize).toBe("typography.xl");
    expect(out.style.borderRadius).toBe("radii.lg");
    expect(out.style.boxShadow).toBe("shadows.md");
    expect(out.unmapped).toHaveLength(0);
  });

  it("returns empty style for empty string", () => {
    const out = tailwindToTokens("");
    expect(out.style).toEqual({});
    expect(out.unmapped).toHaveLength(0);
  });
});
