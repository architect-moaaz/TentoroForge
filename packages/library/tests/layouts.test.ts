import { describe, it, expect } from "vitest";
import { LayoutTemplate } from "@tentoroforge/schema";
import { layouts } from "../src/layouts";

describe("layouts", () => {
  it("DashboardLayout parses cleanly", () => {
    expect(() => LayoutTemplate.parse(layouts.DashboardLayout)).not.toThrow();
  });

  it("AuthLayout parses cleanly", () => {
    expect(() => LayoutTemplate.parse(layouts.AuthLayout)).not.toThrow();
  });

  it("DashboardLayout has 'main' and 'sidebar' Slots", () => {
    const json = JSON.stringify(layouts.DashboardLayout);
    expect(json).toContain('"name":"main"');
    expect(json).toContain('"name":"sidebar"');
  });

  it("AuthLayout has a 'main' Slot", () => {
    const json = JSON.stringify(layouts.AuthLayout);
    expect(json).toContain('"name":"main"');
  });

  it("DashboardLayout is version 1", () => {
    expect(layouts.DashboardLayout.schemaVersion).toBe("1");
  });

  it("AuthLayout is version 1", () => {
    expect(layouts.AuthLayout.schemaVersion).toBe("1");
  });
});
