import { describe, it, expect } from "vitest";
import { TokenRef, StyleProps, Tokens } from "../src/tokens";

describe("TokenRef", () => {
  it("accepts the full surface area of LLM-emitted token forms", () => {
    // canonical dotted form (`primary.500`)
    expect(TokenRef.parse("primary.500")).toBe("primary.500");
    expect(TokenRef.parse("spacing.4")).toBe("spacing.4");
    // newer scoped form (`tokens.<scope>.<...path>`)
    expect(TokenRef.parse("tokens.spacing.1")).toBe("tokens.spacing.1");
    expect(TokenRef.parse("tokens.color.surface.0")).toBe("tokens.color.surface.0");
    // semantic short tokens used throughout the design system
    expect(TokenRef.parse("lg")).toBe("lg");
    expect(TokenRef.parse("primary")).toBe("primary");
    // Mustache-template indirection
    expect(TokenRef.parse("{{theme.gap}}")).toBe("{{theme.gap}}");
  });

  it("rejects empty values", () => {
    expect(() => TokenRef.parse("")).toThrow();
  });
});

describe("StyleProps", () => {
  it("accepts mixed token forms in style fields", () => {
    // dotted, scoped, and short forms all flow through
    expect(() =>
      StyleProps.parse({ color: "primary.500", padding: "spacing.4" }),
    ).not.toThrow();
    expect(() =>
      StyleProps.parse({ color: "tokens.color.primary.500", gap: "lg" }),
    ).not.toThrow();
  });

  it("rejects unknown keys", () => {
    expect(() => StyleProps.parse({ unknownKey: "primary.500" })).toThrow();
  });
});

describe("design tokens — surface depth", () => {
  it("accepts surface.gradient.subtle as a linear gradient definition", () => {
    const r = Tokens.safeParse({
      surface: {
        "0": "#fff",
        gradient: {
          subtle: { type: "linear", angle: 135, from: "tokens.color.accent.50", to: "tokens.color.surface.0" },
        },
      },
    });
    expect(r.success).toBe(true);
  });

  it("accepts surface.shadow.elevated as a CSS shadow string", () => {
    const r = Tokens.safeParse({
      surface: {
        "0": "#fff",
        shadow: { elevated: "0 8px 24px -8px rgba(15, 23, 42, 0.18)" },
      },
    });
    expect(r.success).toBe(true);
  });

  it("rejects a gradient with angle out of [0..360]", () => {
    const r = Tokens.safeParse({
      surface: {
        gradient: { broken: { type: "linear", angle: 720, from: "#fff", to: "#000" } },
      },
    });
    expect(r.success).toBe(false);
  });

  it("legacy tokens (no surface.gradient/shadow) still validate", () => {
    const r = Tokens.safeParse({ surface: { "0": "#fff", "50": "#f8fafc" } });
    expect(r.success).toBe(true);
  });
});
