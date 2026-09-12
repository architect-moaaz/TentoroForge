import { describe, it, expect } from "vitest";
import { resolveIcon } from "../src/icons";

// A nav item or tile carries an icon name chosen upstream — by an agent
// composing the navigation, by A2UI naming a surface — from a vocabulary
// larger than the set the library imports. Names like `plus-circle` and
// `table` are not in ICON_MAP, and once rendered a blank spacer the sidebar
// came up as empty circles beside real routes. resolveIcon must fold the
// common shape suffixes and structural synonyms onto an imported glyph.
describe("resolveIcon — near-miss names still draw something", () => {
  it("exact names still resolve", () => {
    expect(resolveIcon("plus")).not.toBeNull();
    expect(resolveIcon("search")).not.toBeNull();
    expect(resolveIcon("layout-grid")).not.toBeNull();
  });

  it("strips a shape suffix: plus-circle -> plus", () => {
    expect(resolveIcon("plus-circle")).toBe(resolveIcon("plus"));
    expect(resolveIcon("check-square")).toBe(resolveIcon("check"));
  });

  it("resolves structural synonyms: table/grid -> a grid glyph", () => {
    expect(resolveIcon("table")).toBe(resolveIcon("layout-grid"));
    expect(resolveIcon("grid")).toBe(resolveIcon("layout-grid"));
    expect(resolveIcon("dashboard")).not.toBeNull();
  });

  it("is case- and whitespace-insensitive", () => {
    expect(resolveIcon("  Plus-Circle ")).toBe(resolveIcon("plus"));
  });

  it("a genuinely unknown name is still null", () => {
    expect(resolveIcon("definitely-not-an-icon-xyz")).toBeNull();
    expect(resolveIcon("")).toBeNull();
    expect(resolveIcon(null)).toBeNull();
  });
});
