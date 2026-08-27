import { describe, it, expect } from "vitest";
import { layouts } from "../../src/layouts/index";
import { LayoutTemplate } from "@tentoroforge/schema";

/**
 * Walks a layout's root tree and collects every Slot node's `name` prop.
 * This is the canonical way to enumerate a layout's slots — they live in
 * the rendered tree, not in a separate metadata field.
 */
function collectSlotNames(node: any, out: string[] = []): string[] {
  if (!node || typeof node !== "object") return out;
  if (node.type === "Slot" && node.props?.name) out.push(node.props.name);
  if (Array.isArray(node.children)) {
    for (const c of node.children) collectSlotNames(c, out);
  }
  return out;
}

describe("layouts registry", () => {
  it("exports MarketingLayout", () => {
    expect(layouts.MarketingLayout).toBeDefined();
    expect(layouts.MarketingLayout.id).toBe("MarketingLayout");
  });

  it("exports SettingsLayout", () => {
    expect(layouts.SettingsLayout).toBeDefined();
    expect(layouts.SettingsLayout.id).toBe("SettingsLayout");
  });

  it("preserves AuthLayout and DashboardLayout (existing layouts)", () => {
    expect(layouts.AuthLayout).toBeDefined();
    expect(layouts.DashboardLayout).toBeDefined();
  });

  it("MarketingLayout root tree has header, content, and footer Slot nodes", () => {
    const slotNames = collectSlotNames(layouts.MarketingLayout.root);
    expect(slotNames).toContain("header");
    expect(slotNames).toContain("content");
    expect(slotNames).toContain("footer");
  });

  it("SettingsLayout root tree has sidebar and content Slot nodes", () => {
    const slotNames = collectSlotNames(layouts.SettingsLayout.root);
    expect(slotNames).toContain("sidebar");
    expect(slotNames).toContain("content");
  });

  it("All layouts parse cleanly through LayoutTemplate schema", () => {
    expect(() => LayoutTemplate.parse(layouts.AuthLayout)).not.toThrow();
    expect(() => LayoutTemplate.parse(layouts.DashboardLayout)).not.toThrow();
    expect(() => LayoutTemplate.parse(layouts.MarketingLayout)).not.toThrow();
    expect(() => LayoutTemplate.parse(layouts.SettingsLayout)).not.toThrow();
  });
});
