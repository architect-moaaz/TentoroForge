import { describe, it, expect } from "vitest";
import { EDITOR_VERSION } from "../src";

describe("editor package", () => {
  it("exports EDITOR_VERSION", () => {
    expect(EDITOR_VERSION).toBe("0.2.0");
  });
});
