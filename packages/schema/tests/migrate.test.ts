import { describe, it, expect } from "vitest";
import { migratePage } from "../src/migrate";
import { PageV2 } from "../src/page";

describe("migratePage", () => {
  it("returns v2 unchanged", () => {
    const v2 = {
      schemaVersion: "2", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "Stack", props: {}, children: [] },
    };
    expect(migratePage(v2)).toEqual(v2);
  });

  it("stamps schemaVersion '2' on a v1 page", () => {
    const v1 = {
      schemaVersion: "1", id: "x", route: "/", layout: "DashboardLayout",
      meta: { title: "X" }, dataSources: [],
      root: { id: "r", type: "Stack", props: {}, children: [] },
    };
    const out = migratePage(v1);
    expect(out.schemaVersion).toBe("2");
    expect(() => PageV2.parse(out)).not.toThrow();
  });

  it("stamps schemaVersion '2' when missing entirely", () => {
    const noVersion = {
      id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "Stack", props: {}, children: [] },
    } as any;
    const out = migratePage(noVersion);
    expect(out.schemaVersion).toBe("2");
  });

  it("preserves children + props during migration", () => {
    const v1 = {
      schemaVersion: "1", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "Stack", props: { gap: "md" },
              children: [{ id: "h", type: "Heading",
                           props: { content: "Hi", level: 1 } }] },
    };
    const out = migratePage(v1);
    const root = out.root as { children: Array<{ props: { content: string } }> };
    expect(root.children[0].props.content).toBe("Hi");
  });
});
