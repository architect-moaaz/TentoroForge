import { describe, it, expect } from "vitest";
import { z } from "zod";
import { canDrop } from "../../src/dnd/validate-drop";

const reg = {
  has: (n: string) => ["Button", "Card", "Spacer", "Stack"].includes(n),
  get(name: string) {
    return name === "Card" ? { name, acceptsChildren: true, propsSchema: z.object({}).strict() }
         : name === "Stack" ? { name, acceptsChildren: true, propsSchema: z.object({}).strict() }
         : name === "Button" ? { name, acceptsChildren: false, propsSchema: z.object({}).strict() }
         : name === "Spacer" ? { name, acceptsChildren: false, propsSchema: z.object({}).strict() }
         : undefined;
  },
} as any;

const page: any = {
  schemaVersion: "1", id: "p", route: "/",
  root: {
    id: "r", type: "Stack", children: [
      { id: "card", type: "Card", children: [{ id: "btn", type: "Button" }] },
      { id: "sp", type: "Spacer" },
    ],
  },
};

describe("canDrop", () => {
  it("allows a Button drop on a Card (acceptsChildren=true)", () => {
    expect(canDrop({ kind: "palette", libraryName: "Button" }, "card", page, reg)).toBe(true);
  });

  it("forbids a Button drop on a Spacer (acceptsChildren=false)", () => {
    expect(canDrop({ kind: "palette", libraryName: "Button" }, "sp", page, reg)).toBe(false);
  });

  it("forbids dropping a node on itself", () => {
    expect(canDrop({ kind: "node", id: "card" }, "card", page, reg)).toBe(false);
  });

  it("forbids dropping a node on its descendant (cycle)", () => {
    expect(canDrop({ kind: "node", id: "card" }, "btn", page, reg)).toBe(false);
  });

  it("forbids reserved type as library palette item", () => {
    expect(canDrop({ kind: "palette", libraryName: "Slot" }, "card", page, reg)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// v2 layout-node child-count contract tests (Task 33)
// Each fixture mirrors the schema constraint enforced by layout-v2.ts:
//   Tabs   — children.length must equal props.tabs.length
//   Split  — exactly 2 children
//   Sidebar— exactly 2 children
//   Form   — rejects ALL child drops (content lives in props.fields)
//   Custom — rejects ALL child drops (content lives in props.html)
// ---------------------------------------------------------------------------

const v2Page: any = {
  schemaVersion: "1", id: "p2", route: "/v2",
  root: {
    id: "root2", type: "Stack", children: [
      // Tabs with 2 tab defs but only 1 child — room for one more
      {
        id: "tabs",
        type: "Tabs",
        props: { tabs: [{ id: "a", label: "A" }, { id: "b", label: "B" }], value: "a" },
        children: [{ id: "t1", type: "Box", children: [] }],
      },
      // Tabs already at capacity (1 tab def, 1 child)
      {
        id: "tabs-full",
        type: "Tabs",
        props: { tabs: [{ id: "a", label: "A" }], value: "a" },
        children: [{ id: "t-full-1", type: "Box", children: [] }],
      },
      // Split with 2 children — full
      {
        id: "split-full",
        type: "Split",
        props: { ratio: "1:1" },
        children: [{ id: "sp1", type: "Box", children: [] }, { id: "sp2", type: "Box", children: [] }],
      },
      // Split with 1 child — room for one more
      {
        id: "split-room",
        type: "Split",
        props: { ratio: "1:1" },
        children: [{ id: "sp3", type: "Box", children: [] }],
      },
      // Sidebar with 2 children — full
      {
        id: "sidebar-full",
        type: "Sidebar",
        props: { width: "240px" },
        children: [{ id: "sb1", type: "Box", children: [] }, { id: "sb2", type: "Box", children: [] }],
      },
      // Form — content lives in props.fields, no children
      {
        id: "form",
        type: "Form",
        props: {
          workflow: "submit-form",
          fields: [{ kind: "text", name: "email", label: "Email" }],
        },
      },
      // Custom — content lives in props.html
      {
        id: "custom",
        type: "Custom",
        props: { html: "<p>hello</p>" },
      },
      // A loose node used as a "node payload" in re-parenting tests
      { id: "loose-box", type: "Box", children: [] },
    ],
  },
};

describe("canDrop — v2 layout child-count contracts", () => {
  // 1. Tabs — under-filled: palette drop allowed
  it("allows a palette drop on an under-filled Tabs node", () => {
    expect(canDrop({ kind: "palette", libraryName: "Card" }, "tabs", v2Page, reg)).toBe(true);
  });

  // 2. Tabs — at capacity: palette drop rejected
  it("rejects a palette drop on a full Tabs node", () => {
    expect(canDrop({ kind: "palette", libraryName: "Card" }, "tabs-full", v2Page, reg)).toBe(false);
  });

  // 3. Split — full: node (re-parent) drop rejected
  it("rejects a node drop on a full Split node", () => {
    expect(canDrop({ kind: "node", id: "loose-box" }, "split-full", v2Page, reg)).toBe(false);
  });

  // 4. Split — room: node drop allowed
  it("allows a node drop on an under-filled Split node", () => {
    expect(canDrop({ kind: "node", id: "loose-box" }, "split-room", v2Page, reg)).toBe(true);
  });

  // 5. Sidebar — full: palette drop rejected
  it("rejects a palette drop on a full Sidebar node", () => {
    expect(canDrop({ kind: "palette", libraryName: "Button" }, "sidebar-full", v2Page, reg)).toBe(false);
  });

  // 6. Form — always rejects child drops (its content is in props.fields, not children)
  it("rejects a palette Button drop on a Form node", () => {
    expect(canDrop({ kind: "palette", libraryName: "Button" }, "form", v2Page, reg)).toBe(false);
  });

  // 7. Custom — always rejects child drops (its content is in props.html)
  it("rejects a palette drop on a Custom node", () => {
    expect(canDrop({ kind: "palette", libraryName: "Card" }, "custom", v2Page, reg)).toBe(false);
  });

  // 8. Custom — re-parenting a node onto Custom is also rejected
  it("rejects a node (re-parent) drop on a Custom node", () => {
    expect(canDrop({ kind: "node", id: "loose-box" }, "custom", v2Page, reg)).toBe(false);
  });
});
