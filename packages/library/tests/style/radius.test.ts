import { describe, it, expect } from "vitest";
import { RADIUS_SURFACE_CLASS, RADIUS_PILL_CLASS } from "../../src/style/radius";

describe("radius lookup tables", () => {
  it("RADIUS_SURFACE_CLASS maps each scale to the expected Tailwind class", () => {
    expect(RADIUS_SURFACE_CLASS.sharp).toBe("rounded-none");
    expect(RADIUS_SURFACE_CLASS.soft).toBe("rounded-lg");
    expect(RADIUS_SURFACE_CLASS.round).toBe("rounded-2xl");
  });

  it("RADIUS_PILL_CLASS is constant — pill is not scale-dependent", () => {
    expect(RADIUS_PILL_CLASS).toBe("rounded-full");
  });
});
