import { describe, it, expect } from "vitest";
import { SCHEMA_VERSION } from "../src";

describe("schema package", () => {
  it("exports SCHEMA_VERSION = '1'", () => {
    expect(SCHEMA_VERSION).toBe("1");
  });
});
