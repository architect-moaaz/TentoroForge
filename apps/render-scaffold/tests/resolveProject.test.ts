import { describe, it } from "node:test";
import assert from "node:assert";
import { resolveProject } from "../src/lib/resolveProject";

describe("resolveProject", () => {
  it("rejects path traversal", () => {
    assert.throws(() => resolveProject("../etc"), /invalid project id/);
    assert.throws(() => resolveProject("a/b"), /invalid project id/);
    assert.throws(() => resolveProject(".hidden"), /invalid project id/);
  });

  it("returns the absolute path under output/", () => {
    const result = resolveProject("test-app");
    assert.ok(result.endsWith("/output/test-app"));
  });
});
