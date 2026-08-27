import { describe, it, expect } from "vitest";
import { compileTokens } from "@tentoroforge/renderer";
import { defaultTokens } from "../src/theme/default-tokens";

/**
 * Verifies that compileTokens emits CSS vars for all Wave 2 token groups.
 *
 * Note on var naming: compileTokens drops the top-level group key (matching
 * existing behavior where `radius.sm` → `--token-sm`, not `--token-radius-sm`).
 * Top-level scalars (density, elevation, motionLevel) emit as `--token-<key>`.
 * Nested sub-keys emit as `--token-<subkey>(-<leaf>)`.
 */
describe("compileTokens — Wave 2 new groups", () => {
  const css = compileTokens(defaultTokens as any);

  it("emits density as a flat var", () => {
    expect(css["--token-density"]).toBe("comfortable");
  });

  it("emits elevation as a flat var", () => {
    expect(css["--token-elevation"]).toBe("layered");
  });

  it("emits motionLevel as a flat var", () => {
    expect(css["--token-motionLevel"]).toBe("subtle");
  });

  it("emits radius.scale var", () => {
    expect(css["--token-scale"]).toBe("soft");
  });

  it("emits typography.display.family", () => {
    expect(css["--token-display-family"]).toContain("Inter");
  });

  it("emits typography.display.weight", () => {
    expect(css["--token-display-weight"]).toBe("700");
  });

  it("emits typography.bodyText.lineHeight", () => {
    expect(css["--token-bodyText-lineHeight"]).toBe("1.5");
  });

  it("emits typography.numeric.tabular", () => {
    expect(css["--token-numeric-tabular"]).toBe("false");
  });

  it("emits typography.scaleMode", () => {
    expect(css["--token-scaleMode"]).toBe("balanced");
  });

  it("emits token vars for existing groups (pre-existing group-prefix-drop behavior)", () => {
    // radius.sm and shadow.sm both map to --token-sm; last writer wins (pre-existing behavior)
    expect(css["--token-sm"]).toBeDefined();
    expect(css["--token-md"]).toBeDefined();
    // radius.full has no collision — confirms radius group is emitted
    expect(css["--token-full"]).toBe("9999px");
  });

  it("preserves existing motion animation vars", () => {
    expect(css["--token-duration-fast"]).toBe("150ms");
    expect(css["--token-duration-normal"]).toBe("300ms");
    expect(css["--token-easing-standard"]).toBe("cubic-bezier(0.4, 0, 0.2, 1)");
  });

  it("preserves existing color vars (legacy flat-map pattern)", () => {
    // color.primary.500 stored as "primary.500" key inside the group → --token-primary-500
    expect(css["--token-primary-500"]).toBe("#3b82f6");
  });
});
