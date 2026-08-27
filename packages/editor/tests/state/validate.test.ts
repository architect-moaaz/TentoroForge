import { describe, it, expect } from "vitest";
import { validateSchema } from "../../src/state/validate";

describe("validateSchema", () => {
  it("returns no errors for a valid Page", () => {
    const errs = validateSchema({
      schemaVersion: "1", id: "p", route: "/",
      root: { id: "r", type: "Box", children: [] },
    } as any);
    expect(errs).toEqual([]);
  });

  it("returns errors for missing root", () => {
    const errs = validateSchema({ schemaVersion: "1", id: "p", route: "/" } as any);
    expect(errs.length).toBeGreaterThan(0);
    expect(errs[0].path).toContain("root");
  });
});
