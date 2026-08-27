import { describe, it, expect } from "vitest";
import { renderToObject } from "../src/test-harness/renderToObject";

describe("renderToObject", () => {
  it("returns a tree object for a leaf node", () => {
    const out = renderToObject({
      schemaVersion: "1",
      id: "p",
      route: "/",
      root: { id: "r", type: "Box", children: [] },
    } as any);
    expect(out).toMatchObject({ type: "Box", id: "r" });
  });
});
