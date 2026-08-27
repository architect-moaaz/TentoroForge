import { describe, it, expect } from "vitest";
import { ButtonProps } from "../../src/components/Button/Button.schema";

describe("Button schema", () => {
  it("accepts a labeled button with an icon", () => {
    const r = ButtonProps.safeParse({ label: "Add", icon: "plus" });
    expect(r.success).toBe(true);
  });

  it("accepts icon-only when aria-label is set", () => {
    const r = ButtonProps.safeParse({ icon: "more-horizontal", "aria-label": "More" });
    expect(r.success).toBe(true);
  });

  it("accepts icon-only (no aria-label required — schema is intentionally permissive for MCP-derived props)", () => {
    // The superRefine requiring aria-label on icon-only buttons was removed so
    // that MCP-derived schemas with partial props render instead of showing
    // "⚠ invalid props". Accessibility is still encouraged via component docs.
    const r = ButtonProps.safeParse({ icon: "more-horizontal" });
    expect(r.success).toBe(true);
  });

  it("defaults iconPosition to left", () => {
    const r = ButtonProps.safeParse({ label: "X", icon: "plus" });
    if (r.success) {
      expect((r.data as any).iconPosition).toBe("left");
    } else {
      throw new Error("parse should succeed");
    }
  });
});
