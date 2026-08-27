import { describe, it, expect } from "vitest";
import { Box, Text, Image } from "../src/primitives/index";

describe("Library primitives re-exports", () => {
  it("exports Box from renderer", () => {
    expect(Box).toBeDefined();
    expect(typeof Box).toBe("function");
  });

  it("exports Text from renderer", () => {
    expect(Text).toBeDefined();
    expect(typeof Text).toBe("function");
  });

  it("exports Image from renderer", () => {
    expect(Image).toBeDefined();
    expect(typeof Image).toBe("function");
  });
});
