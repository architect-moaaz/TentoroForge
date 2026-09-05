import { describe, it, expect } from "vitest";
import {
  NODE_CATEGORIES, WORKFLOW_NODE_CATALOG, missingConfig, visualFor,
} from "./workflowNodes";

describe("workflow node catalog", () => {
  it("drives the palette: every palette item is a catalog node, in catalog categories", () => {
    const types = new Set(WORKFLOW_NODE_CATALOG.nodes.map((n) => n.type));
    expect(NODE_CATEGORIES.map((c) => c.label)).toEqual(
      WORKFLOW_NODE_CATALOG.categories.map((c) => c.label));
    for (const cat of NODE_CATEGORIES) {
      for (const item of cat.nodes) expect(types.has(item.type)).toBe(true);
    }
  });

  it("offers one palette entry per variant, carrying the variant's config", () => {
    const actions = NODE_CATEGORIES.find((c) => c.label === "Actions")!.nodes;
    const insert = actions.find((n) => n.id === "action-db_insert")!;
    expect(insert.type).toBe("action");
    expect(insert.defaultConfig).toEqual({ actionType: "db_insert" });
    const manual = NODE_CATEGORIES[0].nodes.find((n) => n.id === "trigger-manual")!;
    expect(manual.defaultConfig).toEqual({ type: "manual" });
  });

  it("keeps runtime-only aliases out of the palette", () => {
    const ids = NODE_CATEGORIES.flatMap((c) => c.nodes.map((n) => n.id));
    expect(ids).toContain("end");
    expect(ids).not.toContain("end_event");
  });

  it("gives a node the visual of its variant", () => {
    expect(visualFor("action", { actionType: "db_insert" }).icon).toBe("Database");
    expect(visualFor("trigger", { type: "schedule" }).icon).toBe("Calendar");
    expect(visualFor("user_task").icon).toBe("ClipboardCheck");
    // legacy: an action whose actionType is a node type shows that node
    expect(visualFor("action", { actionType: "ai_generate" }).icon).toBe("Sparkles");
    expect(visualFor("nonsense").icon).toBe("Play");
  });

  it("names the configuration a node still needs", () => {
    expect(missingConfig("action", { actionType: "db_insert", table: "t" })).toEqual(["values"]);
    expect(missingConfig("action", { actionType: "db_insert", table: "t", values: { a: 1 } })).toEqual([]);
    expect(missingConfig("approval", {})).toEqual(["assignType", "assignTarget|assignVariablePath"]);
    expect(missingConfig("end", {})).toEqual([]);
  });
});
