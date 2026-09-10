import { describe, it, expect } from "vitest";
import { applyStyleSlot, isColorTokenRef, isScaleTokenRef } from "../src/runtime/style-slot";

// The editor's Background control writes either a token ref or a raw CSS fill
// into the same `style.background` key. Token-wrapping a raw value produced
// `var(--token-#3b82f6)`, which the browser drops silently — the fill just
// never painted. These lock the discrimination in both directions.
describe("applyStyleSlot background", () => {
  it("compiles a token ref to its CSS var", () => {
    const out = applyStyleSlot({ background: "color.primary.500" } as any);
    expect(out.style?.background).toBe("var(--token-color-primary-500)");
  });

  it("strips the tokens. prefix from a token ref", () => {
    const out = applyStyleSlot({ background: "tokens.color.surface.0" } as any);
    expect(out.style?.background).toBe("var(--token-color-surface-0)");
  });

  it("emits a hex colour verbatim", () => {
    const out = applyStyleSlot({ background: "#3b82f6" } as any);
    expect(out.style?.background).toBe("#3b82f6");
  });

  it("emits a CSS named colour verbatim", () => {
    const out = applyStyleSlot({ background: "rebeccapurple" } as any);
    expect(out.style?.background).toBe("rebeccapurple");
  });

  it("emits functional and multi-part CSS fills verbatim", () => {
    for (const raw of [
      "rgb(59 130 246)",
      "rgba(0, 0, 0, 0.5)",
      "hsl(230 30% 10% / 0.62)",
      "linear-gradient(to bottom, white, black)",
      "transparent",
      "var(--custom-fill)",
    ]) {
      expect(applyStyleSlot({ background: raw } as any).style?.background).toBe(raw);
    }
  });

  it("applies the same rule inside the structured solid/gradient forms", () => {
    const solidToken = applyStyleSlot({
      background: { type: "solid", value: "color.primary.500" },
    } as any);
    expect(solidToken.style?.background).toBe("var(--token-color-primary-500)");

    const solidRaw = applyStyleSlot({ background: { type: "solid", value: "#3b82f6" } } as any);
    expect(solidRaw.style?.background).toBe("#3b82f6");

    const gradient = applyStyleSlot({
      background: { type: "gradient", from: "#000000", to: "color.accent.500", angle: 90 },
    } as any);
    expect(gradient.style?.background).toBe(
      "linear-gradient(90deg, #000000 0%, var(--token-color-accent-500) 100%)",
    );
  });
});

// motion.css owns the whole `animation` shorthand, so a per-node duration can
// only reach it through the --motion-duration custom property it reads as a
// fallback. Emitting an `animationDuration` longhand instead would be silently
// overwritten by that shorthand.
describe("applyStyleSlot motion duration", () => {
  it("emits data-motion and --motion-duration when both are set", () => {
    const out = applyStyleSlot({ motion: "slide-in", motionDuration: "1s" } as any);
    expect(out["data-motion"]).toBe("slide-in");
    expect((out.style as any)?.["--motion-duration"]).toBe("1s");
  });

  it("emits data-motion but no custom property when duration is absent", () => {
    const out = applyStyleSlot({ motion: "fade-up" } as any);
    expect(out["data-motion"]).toBe("fade-up");
    expect((out.style as any)?.["--motion-duration"]).toBeUndefined();
  });

  it("emits neither when there is no motion", () => {
    const out = applyStyleSlot({ motionDuration: "500ms" } as any);
    expect(out["data-motion"]).toBeUndefined();
    expect((out.style as any)?.["--motion-duration"]).toBeUndefined();
  });

  it("emits neither for motion:none, even with a duration set", () => {
    const out = applyStyleSlot({ motion: "none", motionDuration: "500ms" } as any);
    expect(out["data-motion"]).toBeUndefined();
    expect((out.style as any)?.["--motion-duration"]).toBeUndefined();
  });

  it("does not disturb the other style keys it shares the object with", () => {
    const out = applyStyleSlot({
      motion: "stagger",
      motionDuration: "250ms",
      background: "#3b82f6",
      width: "240px",
    } as any);
    expect(out.style?.background).toBe("#3b82f6");
    expect(out.style?.width).toBe("240px");
    expect((out.style as any)["--motion-duration"]).toBe("250ms");
  });
});

// The two predicates differ on ONE case — a bare word — and that difference is
// load-bearing in both directions. Colour keys must read "rebeccapurple" as a
// literal; scale keys must read "md" as a token, because live schemas carry
// `"gap": "md"` and `"padding": "md"` that resolve through compileTokens'
// name-only alias.
describe("isColorTokenRef", () => {
  it("accepts dotted identifier paths", () => {
    expect(isColorTokenRef("color.primary.500")).toBe(true);
    expect(isColorTokenRef("tokens.color.surface.0")).toBe(true);
    expect(isColorTokenRef("radius.md")).toBe(true);
  });

  it("rejects every raw-colour syntax, bare colour names included", () => {
    for (const raw of [
      "#fff",
      "#3b82f6",
      "#3b82f6ff",
      "rebeccapurple",
      "white",
      "transparent",
      "rgb(59 130 246)",
      "hsl(210 20% 98%)",
      "linear-gradient(to bottom, white, black)",
      "var(--x)",
      "",
    ]) {
      expect(isColorTokenRef(raw), `${raw} is not a token ref`).toBe(false);
    }
  });
});

describe("isScaleTokenRef", () => {
  it("accepts bare scale names as well as dotted paths", () => {
    for (const ref of ["md", "lg", "xs", "sharp_2", "spacing.4", "tokens.spacing.6"]) {
      expect(isScaleTokenRef(ref), `${ref} is a token ref`).toBe(true);
    }
  });

  it("rejects raw CSS values and bare CSS keywords", () => {
    for (const raw of [
      "788px", "30%", "1.5", "0", "-0.01em", "1rem",
      "0 1px 2px rgb(0 0 0 / 0.05)",
      "auto", "none", "normal", "bold", "inherit",
      "",
    ]) {
      expect(isScaleTokenRef(raw), `${raw} is not a token ref`).toBe(false);
    }
  });
});

describe("applyStyleSlot position", () => {
  it("returns no position keys for legacy styleSlot", () => {
    const result = applyStyleSlot({ spacing: { padding: "md" } } as any);
    expect(result.style?.position).toBeUndefined();
    expect((result.style as any)?.top).toBeUndefined();
  });

  it("emits position:absolute when set", () => {
    const result = applyStyleSlot({
      position: { type: "absolute", top: "16px", right: "24px" },
    } as any);
    expect(result.style?.position).toBe("absolute");
    expect((result.style as any)?.top).toBe("16px");
    expect((result.style as any)?.right).toBe("24px");
  });

  it("emits zIndex when set", () => {
    const result = applyStyleSlot({
      position: { type: "absolute", zIndex: 10 },
    } as any);
    expect((result.style as any)?.zIndex).toBe(10);
  });

  it("emits sticky and fixed correctly", () => {
    const sticky = applyStyleSlot({ position: { type: "sticky", top: "0" } } as any);
    expect(sticky.style?.position).toBe("sticky");
    const fixed = applyStyleSlot({ position: { type: "fixed", bottom: "0", left: "0" } } as any);
    expect(fixed.style?.position).toBe("fixed");
  });
});
