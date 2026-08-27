import { describe, it, expect } from "vitest";
import { StyleSlot, Background } from "../src/style-slot";

describe("StyleSlot", () => {
  it("accepts an empty object", () => {
    expect(StyleSlot.parse({}).motion).toBeUndefined();
  });

  it("accepts gradient background with token refs", () => {
    const r = StyleSlot.parse({
      background: { type: "gradient",
                    from: "tokens.color.primary.50",
                    to: "tokens.color.surface.0",
                    angle: 135 },
      padding: "tokens.spacing.semantic.section",
      radius: "tokens.radius.lg",
      shadow: "tokens.shadow.md",
      motion: "fade-in",
    });
    expect(r.background?.type).toBe("gradient");
    expect(r.motion).toBe("fade-in");
  });

  // Token-form validation moved out of the schema layer (see tokens.ts).
  // Raw values are now accepted at parse time — leaf-token validation is
  // performed by cross-ref-validator + the runtime token resolver.
  it("accepts raw values in token-ref slots (validation deferred)", () => {
    expect(() => StyleSlot.parse({ padding: "16px" })).not.toThrow();
    expect(() => StyleSlot.parse({ padding: "lg" })).not.toThrow();
  });

  it("rejects unknown background type", () => {
    expect(() => StyleSlot.parse({ background: { type: "video", url: "x" } })).toThrow();
  });

  it("Background pattern accepts named patterns only", () => {
    expect(() => Background.parse({ type: "pattern", name: "stripes" })).toThrow();
    expect(Background.parse({ type: "pattern", name: "dots" }).name).toBe("dots");
  });

  // Prefix-only paths used to be rejected by regex; they're now accepted
  // structurally and flagged later by cross-ref-validator if they don't
  // resolve to a real token leaf at render time.
  it("accepts prefix-only token paths (leaf check deferred to validator)", () => {
    expect(() => StyleSlot.parse({ padding: "tokens.spacing." })).not.toThrow();
    expect(() =>
      StyleSlot.parse({ background: { type: "solid", value: "tokens.color." } }),
    ).not.toThrow();
  });

  // StyleSlot was relaxed from strict() to passthrough() so LLM-emitted
  // shorthand style props (`marginTop`, `borderTop`, `gap`, etc.) don't fail
  // validation. Extras flow through to the renderer's resolveStyle, which
  // ignores keys it doesn't know.
  it("accepts unknown keys (passthrough mode)", () => {
    expect(() => StyleSlot.parse({ marginTop: "16px" })).not.toThrow();
    expect(() => StyleSlot.parse({ unknown: "x" })).not.toThrow();
  });
});

describe("StyleSlot position fields", () => {
  it("legacy style without position still parses", () => {
    const result = StyleSlot.safeParse({ spacing: { padding: "md" } });
    expect(result.success).toBe(true);
  });

  it("accepts position with all directional fields", () => {
    const result = StyleSlot.safeParse({
      position: {
        type: "absolute",
        top: "16px",
        right: "24px",
        bottom: "auto",
        left: "auto",
        zIndex: 10,
      },
    });
    expect(result.success).toBe(true);
  });

  it("position.type accepts relative, absolute, fixed, sticky", () => {
    for (const t of ["relative", "absolute", "fixed", "sticky"]) {
      const r = StyleSlot.safeParse({ position: { type: t } });
      expect(r.success, `type=${t} should parse`).toBe(true);
    }
  });

  it("position.type rejects invalid values", () => {
    const r = StyleSlot.safeParse({ position: { type: "floating" } });
    expect(r.success).toBe(false);
  });

  it("position fields are all optional", () => {
    const r = StyleSlot.safeParse({ position: { type: "absolute" } });
    expect(r.success).toBe(true);
  });

  it("zIndex accepts number, rejects string", () => {
    const ok = StyleSlot.safeParse({ position: { type: "absolute", zIndex: 5 } });
    expect(ok.success).toBe(true);
    const bad = StyleSlot.safeParse({ position: { type: "absolute", zIndex: "5" } });
    expect(bad.success).toBe(false);
  });
});
