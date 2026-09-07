import { describe, it, expect } from "vitest";
import { pickResponsiveValue } from "../src/responsive/useViewport";

describe("pickResponsiveValue", () => {
  it("returns the exact-bp value", () => {
    expect(pickResponsiveValue({ default: "a", md: "b" }, "md")).toBe("b");
  });

  it("falls back to a smaller bp", () => {
    expect(pickResponsiveValue({ default: "a", md: "b" }, "lg")).toBe("b");
  });

  it("falls back to default when no smaller bp set", () => {
    expect(pickResponsiveValue({ default: "a" }, "xl")).toBe("a");
  });

  it("returns string literals unchanged", () => {
    expect(pickResponsiveValue("plain", "md")).toBe("plain");
  });

  it("returns number literals unchanged", () => {
    expect(pickResponsiveValue(42, "md")).toBe(42);
  });

  it("returns array literals unchanged", () => {
    expect(pickResponsiveValue(["a", "b"], "md")).toEqual(["a", "b"]);
  });

  it("does NOT mistake { url, overlay } for a responsive shape", () => {
    const bg = { url: "https://example.com/x.jpg", overlay: 0.4 };
    expect(pickResponsiveValue(bg, "md")).toBe(bg);
  });

  it("does NOT mistake { name, level } for a responsive shape", () => {
    const heading = { name: "h1", level: 1 };
    expect(pickResponsiveValue(heading, "md")).toBe(heading);
  });

  it("handles null + undefined", () => {
    expect(pickResponsiveValue(null as any, "md")).toBe(null);
    expect(pickResponsiveValue(undefined as any, "md")).toBe(undefined);
  });

  it("handles empty bp objects", () => {
    expect(pickResponsiveValue({}, "md")).toEqual({});
  });
});
