import { describe, it, expect } from "vitest";
import { buildDefaultRegistry } from "../src/buildDefaultRegistry";

/**
 * Regression for the "⚠ <Type>: invalid props" failures seen in Figma-generated
 * apps. The Figma mapper puts a Tailwind `className` on every node and uses
 * prop shapes (`content`, `label`, `iconSrc`) that strict component schemas
 * rejected. validateProps now sets `className` aside (preserving it) and the
 * NavLink/IconButton schemas accept the pipeline's shapes.
 */
describe("validateProps — Figma-style props validate and preserve className", () => {
  const reg = buildDefaultRegistry();

  it("Badge {className, content} → valid, className preserved", () => {
    const v = reg.validateProps("Badge", {
      className: "rounded-md py-0.5 px-2 bg-[#faf5ff] text-xs",
      content: "14:00 - 16:00",
    });
    expect(v.content).toBe("14:00 - 16:00");
    expect(v.className).toBe("rounded-md py-0.5 px-2 bg-[#faf5ff] text-xs");
  });

  it("NavLink {className, label} → valid (was: href/children required)", () => {
    const v = reg.validateProps("NavLink", { className: "px-3 py-2", label: "Dashboard" });
    expect((v.label ?? v.children)).toBe("Dashboard");
    expect(v.className).toBe("px-3 py-2");
  });

  it("IconButton {className, iconSrc} → valid (was: icon/aria-label required)", () => {
    const v = reg.validateProps("IconButton", { className: "w-9 h-9", iconSrc: "/api/asset/x.svg" });
    expect(v.iconSrc).toBe("/api/asset/x.svg");
    expect(v.className).toBe("w-9 h-9");
  });

  it("className is preserved on a formerly-strict schema without per-schema edits", () => {
    // Divider is .strict() and declares no className; validateProps preserves it.
    const v = reg.validateProps("Divider", { className: "my-4 border-gray-200" });
    expect(v.className).toBe("my-4 border-gray-200");
  });

  it("data-* props are preserved like className on strict schemas", () => {
    const v = reg.validateProps("Cluster", {
      className: "dashboard-toolbar",
      "data-dashboard-toolbar": "",
      "data-testid": "toolbar",
      align: "end",
    });
    expect(v.className).toBe("dashboard-toolbar");
    expect(v["data-dashboard-toolbar"]).toBe("");
    expect(v["data-testid"]).toBe("toolbar");
    expect(v.align).toBe("end");
  });
});
