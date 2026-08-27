import { describe, it, expect } from "vitest";
import { formatValue, isUuid } from "../src/utils/formatValue";

describe("formatValue", () => {
  it("passes strings through and empties null/undefined", () => {
    expect(formatValue("hi")).toBe("hi");
    expect(formatValue(null)).toBe("");
    expect(formatValue(undefined)).toBe("");
  });
  it("stringifies numbers and booleans", () => {
    expect(formatValue(5)).toBe("5");
    expect(formatValue(0)).toBe("0");
    expect(formatValue(NaN)).toBe("");
    expect(formatValue(true)).toBe("Yes");
    expect(formatValue(false)).toBe("No");
  });
  it("formats a Date deterministically (ISO date), never crashing", () => {
    expect(formatValue(new Date("2025-01-20T00:00:00Z"))).toBe("2025-01-20");
    expect(formatValue(new Date("invalid"))).toBe("");
  });
  it("stringifies objects instead of throwing", () => {
    expect(formatValue({ a: 1 })).toBe('{"a":1}');
    expect(formatValue({})).toBe("");
  });
});

describe("isUuid", () => {
  it("detects UUIDs", () => {
    expect(isUuid("f40b4dd7-6b6c-4135-95f3-fb403accb28b")).toBe(true);
    expect(isUuid("Bronze")).toBe(false);
    expect(isUuid(5)).toBe(false);
  });
});
