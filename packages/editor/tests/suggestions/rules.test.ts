import { describe, it, expect } from "vitest";
import { rules } from "../../src/suggestions/rules";

// ── iconbutton-aria-label ──────────────────────────────────────────────────
describe("iconbutton-aria-label", () => {
  const rule = rules.find((r) => r.id === "iconbutton-aria-label")!;

  it("flags IconButton without aria-label", () => {
    const node = { id: "b1", type: "IconButton", props: {} };
    const out = rule.check(node, {} as any);
    expect(out.length).toBe(1);
    expect(out[0].severity).toBe("warn");
    expect(out[0].ruleId).toBe("iconbutton-aria-label");
    expect(out[0].nodeId).toBe("b1");
  });

  it("ignores IconButton with aria-label", () => {
    const node = { id: "b2", type: "IconButton", props: { "aria-label": "Close" } };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });

  it("ignores other node types", () => {
    const node = { id: "b3", type: "Button", props: {} };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });
});

// ── repeat-needs-keypath ──────────────────────────────────────────────────
describe("repeat-needs-keypath", () => {
  const rule = rules.find((r) => r.id === "repeat-needs-keypath")!;

  it("flags Repeat without keyPath", () => {
    const node = { id: "r1", type: "Repeat", props: {} };
    const out = rule.check(node, {} as any);
    expect(out.length).toBe(1);
    expect(out[0].severity).toBe("info");
    expect(out[0].ruleId).toBe("repeat-needs-keypath");
  });

  it("ignores Repeat with keyPath", () => {
    const node = { id: "r2", type: "Repeat", props: { keyPath: "id" } };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });

  it("ignores other node types", () => {
    const node = { id: "r3", type: "List", props: {} };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });
});

// ── card-too-many-children ────────────────────────────────────────────────
describe("card-too-many-children", () => {
  const rule = rules.find((r) => r.id === "card-too-many-children")!;
  const makeChildren = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `c${i}`, type: "Text" }));

  it("flags Card with > 6 children", () => {
    const node = { id: "card1", type: "Card", children: makeChildren(7) };
    const out = rule.check(node, {} as any);
    expect(out.length).toBe(1);
    expect(out[0].severity).toBe("info");
    expect(out[0].ruleId).toBe("card-too-many-children");
  });

  it("ignores Card with exactly 6 children", () => {
    const node = { id: "card2", type: "Card", children: makeChildren(6) };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });

  it("ignores other node types", () => {
    const node = { id: "box1", type: "Box", children: makeChildren(10) };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });
});

// ── text-without-content ──────────────────────────────────────────────────
describe("text-without-content", () => {
  const rule = rules.find((r) => r.id === "text-without-content")!;

  it("flags Text with no content and no bind", () => {
    const node = { id: "t1", type: "Text", props: {} };
    const out = rule.check(node, {} as any);
    expect(out.length).toBe(1);
    expect(out[0].severity).toBe("warn");
    expect(out[0].ruleId).toBe("text-without-content");
  });

  it("ignores Text with content prop", () => {
    const node = { id: "t2", type: "Text", props: { content: "Hello" } };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });

  it("ignores Text with bind", () => {
    const node = { id: "t3", type: "Text", props: {}, bind: { field: "name" } };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });

  it("ignores other node types", () => {
    const node = { id: "i1", type: "Image", props: {} };
    const out = rule.check(node, {} as any);
    expect(out).toEqual([]);
  });
});

// ── unknown-token-reference ───────────────────────────────────────────────
describe("unknown-token-reference", () => {
  const rule = rules.find((r) => r.id === "unknown-token-reference")!;
  const ctx = {
    theme: {
      color: { primary: "#3b82f6", secondary: "#6366f1" },
      spacing: { sm: "8px" },
    },
  };

  it("flags style with unknown token reference", () => {
    const node = {
      id: "n1", type: "Box", props: {},
      style: { color: { $token: "color.nonexistent" } },
    };
    const out = rule.check(node, ctx);
    expect(out.length).toBe(1);
    expect(out[0].severity).toBe("warn");
    expect(out[0].ruleId).toBe("unknown-token-reference");
  });

  it("ignores style with valid token reference", () => {
    const node = {
      id: "n2", type: "Box", props: {},
      style: { color: { $token: "color.primary" } },
    };
    const out = rule.check(node, ctx);
    expect(out).toEqual([]);
  });

  it("ignores node with no style", () => {
    const node = { id: "n3", type: "Box", props: {} };
    const out = rule.check(node, ctx);
    expect(out).toEqual([]);
  });

  it("ignores style without token refs", () => {
    const node = {
      id: "n4", type: "Box", props: {},
      style: { color: "#ff0000" },
    };
    const out = rule.check(node, ctx);
    expect(out).toEqual([]);
  });

  it("returns no errors when no theme provided", () => {
    const node = {
      id: "n5", type: "Box", props: {},
      style: { color: { $token: "color.anything" } },
    };
    const out = rule.check(node, {});
    expect(out).toEqual([]);
  });
});
