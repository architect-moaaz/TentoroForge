// packages/library/tests/style/resolveStyle.test.ts
import { describe, it, expect } from "vitest";
import { resolveStyle } from "../../src/style/resolveStyle";

describe("resolveStyle", () => {
  it("returns empty object for undefined slot", () => {
    expect(resolveStyle(undefined)).toEqual({});
  });

  it("maps padding/radius/shadow tokens to CSS vars", () => {
    const r = resolveStyle({
      padding: "tokens.spacing.semantic.section",
      radius:  "tokens.radius.lg",
      shadow:  "tokens.shadow.md",
    });
    expect(r.padding).toBe("var(--token-spacing-semantic-section)");
    expect(r.borderRadius).toBe("var(--token-radius-lg)");
    expect(r.boxShadow).toBe("var(--token-shadow-md)");
  });

  it("maps solid background to CSS var", () => {
    const r = resolveStyle({
      background: { type: "solid", value: "tokens.color.primary.500" },
    });
    expect(r.background).toBe("var(--token-color-primary-500)");
  });

  it("builds gradient with default angle 135", () => {
    const r = resolveStyle({
      background: { type: "gradient",
                    from: "tokens.color.primary.50",
                    to:   "tokens.color.surface.0" },
    });
    expect(r.background).toBe(
      "linear-gradient(135deg, var(--token-color-primary-50) 0%, var(--token-color-surface-0) 100%)"
    );
  });

  it("uses provided angle for gradient", () => {
    expect(
      (resolveStyle({ background: { type: "gradient",
        from: "tokens.color.primary.50", to: "tokens.color.primary.500", angle: 90 } })
        .background as string)
    ).toContain("90deg");
  });

  it("emits image background", () => {
    const r = resolveStyle({
      background: { type: "image", url: "https://example.com/bg.jpg" },
    });
    expect(r.background).toBe(`url("https://example.com/bg.jpg") center/cover`);
  });

  it("respects custom image position", () => {
    const r = resolveStyle({
      background: { type: "image", url: "/bg.jpg", position: "top/contain" },
    });
    expect(r.background).toBe(`url("/bg.jpg") top/contain`);
  });

  it("emits radial-gradient stub for pattern background", () => {
    const r = resolveStyle({
      background: { type: "pattern", name: "dots" },
    });
    expect(r.background as string).toContain("radial-gradient");
  });

  it("uses provided color for pattern background", () => {
    const r = resolveStyle({
      background: { type: "pattern", name: "dots", color: "tokens.color.primary.500" },
    });
    expect(r.background as string).toContain("var(--token-color-primary-500)");
  });
});
