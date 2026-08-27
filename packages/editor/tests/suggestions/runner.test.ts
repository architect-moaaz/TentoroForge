import { describe, it, expect } from "vitest";
import { runRules } from "../../src/suggestions/runner";

const makePage = (root: any): any => ({
  schemaVersion: "1",
  id: "p",
  route: "/",
  root,
});

describe("runRules", () => {
  it("returns empty array for a clean page", () => {
    const page = makePage({
      id: "root",
      type: "Stack",
      children: [
        { id: "btn", type: "Button", props: { label: "Click me" } },
      ],
    });
    const out = runRules(page, {});
    expect(out).toEqual([]);
  });

  it("surfaces iconbutton-aria-label violation", () => {
    const page = makePage({
      id: "root",
      type: "Stack",
      children: [
        { id: "ib", type: "IconButton", props: {} },
      ],
    });
    const out = runRules(page, {});
    expect(out.some((s) => s.ruleId === "iconbutton-aria-label")).toBe(true);
  });

  it("surfaces repeat-needs-keypath violation", () => {
    const page = makePage({
      id: "root",
      type: "Stack",
      children: [
        { id: "rpt", type: "Repeat", props: {} },
      ],
    });
    const out = runRules(page, {});
    expect(out.some((s) => s.ruleId === "repeat-needs-keypath")).toBe(true);
  });

  it("surfaces card-too-many-children violation", () => {
    const children = Array.from({ length: 8 }, (_, i) => ({ id: `c${i}`, type: "Text" }));
    const page = makePage({
      id: "root",
      type: "Stack",
      children: [
        { id: "card1", type: "Card", children },
      ],
    });
    const out = runRules(page, {});
    expect(out.some((s) => s.ruleId === "card-too-many-children")).toBe(true);
  });

  it("surfaces text-without-content violation", () => {
    const page = makePage({
      id: "root",
      type: "Stack",
      children: [
        { id: "txt", type: "Text", props: {} },
      ],
    });
    const out = runRules(page, {});
    expect(out.some((s) => s.ruleId === "text-without-content")).toBe(true);
  });

  it("surfaces unknown-token-reference violation", () => {
    const page = makePage({
      id: "root",
      type: "Stack",
      children: [
        {
          id: "box1",
          type: "Box",
          props: {},
          style: { color: { $token: "color.ghost" } },
        },
      ],
    });
    const ctx = { theme: { color: { primary: "#3b82f6" } } };
    const out = runRules(page, ctx);
    expect(out.some((s) => s.ruleId === "unknown-token-reference")).toBe(true);
  });

  it("walks nested children", () => {
    const page = makePage({
      id: "root",
      type: "Stack",
      children: [
        {
          id: "card",
          type: "Card",
          children: [
            { id: "ib", type: "IconButton", props: {} },
          ],
        },
      ],
    });
    const out = runRules(page, {});
    expect(out.some((s) => s.ruleId === "iconbutton-aria-label")).toBe(true);
  });

  it("surfaces multiple violations in one page", () => {
    const page = makePage({
      id: "root",
      type: "Stack",
      children: [
        { id: "ib", type: "IconButton", props: {} },
        { id: "txt", type: "Text", props: {} },
        { id: "rpt", type: "Repeat", props: {} },
      ],
    });
    const out = runRules(page, {});
    const ruleIds = out.map((s) => s.ruleId);
    expect(ruleIds).toContain("iconbutton-aria-label");
    expect(ruleIds).toContain("text-without-content");
    expect(ruleIds).toContain("repeat-needs-keypath");
  });

  it("accepts a custom rule list", () => {
    const customRule = {
      id: "custom-rule",
      check: (node: any) =>
        node.type === "Box"
          ? [{ id: `custom:${node.id}`, source: "rule" as const, ruleId: "custom-rule", severity: "info" as const, title: "Custom", description: "Custom rule fired" }]
          : [],
    };
    const page = makePage({ id: "root", type: "Box", children: [] });
    const out = runRules(page, {}, [customRule]);
    expect(out.length).toBe(1);
    expect(out[0].ruleId).toBe("custom-rule");
  });
});
