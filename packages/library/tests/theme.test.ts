import { describe, it, expect } from "vitest";
import { defaultTokens } from "../src/theme/default-tokens";

describe("defaultTokens", () => {
  it("contains color/spacing/typography/radius/shadow groups", () => {
    expect(defaultTokens.color).toBeDefined();
    expect(defaultTokens.spacing).toBeDefined();
    expect(defaultTokens.typography).toBeDefined();
    expect(defaultTokens.radius).toBeDefined();
    expect(defaultTokens.shadow).toBeDefined();
  });

  it("provides primary, secondary, accent palettes", () => {
    for (const palette of ["primary", "secondary", "accent"] as const) {
      for (const step of ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"] as const) {
        expect((defaultTokens.color[palette] as any)[step]).toMatch(/^#[0-9a-f]{6}$/i);
      }
    }
  });

  it("provides status color palettes", () => {
    for (const status of ["success", "warning", "error", "info"] as const) {
      for (const step of ["50", "500", "700"] as const) {
        expect((defaultTokens.color[status] as any)[step]).toMatch(/^#[0-9a-f]{6}$/i);
      }
    }
  });

  it("provides spacing and typography scale entries", () => {
    for (const stop of ["0", "1", "2", "3", "4", "6", "8", "12", "16", "24", "32", "48", "64"] as const) {
      expect((defaultTokens.spacing as any)[stop]).toBeDefined();
    }
    for (const key of ["h1", "h2", "h3", "body", "caption"] as const) {
      expect(defaultTokens.typography.scale[key]).toBeDefined();
    }
  });
});
