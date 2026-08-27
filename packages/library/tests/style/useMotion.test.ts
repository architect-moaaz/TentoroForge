import { describe, it, expect } from "vitest";
import { useMotion } from "../../src/style/useMotion";

describe("useMotion", () => {
  it("returns empty object for undefined", () => {
    expect(useMotion(undefined)).toEqual({});
  });

  it("returns empty object for 'none'", () => {
    expect(useMotion("none")).toEqual({});
  });

  it("returns data-motion attribute for fade-in", () => {
    expect(useMotion("fade-in")).toEqual({ "data-motion": "fade-in" });
  });

  it("returns data-motion attribute for stagger", () => {
    expect(useMotion("stagger")).toEqual({ "data-motion": "stagger" });
  });
});
