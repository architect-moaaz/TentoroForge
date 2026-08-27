import { describe, it, expect } from "vitest";
import { normalizeWorkflowNodes } from "./normalize-nodes";
import type { WorkflowNodeSerialized } from "@/types/workflow";

const node = (over: Partial<WorkflowNodeSerialized>): WorkflowNodeSerialized => ({
  id: "n",
  type: "action",
  position: { x: 0, y: 0 },
  data: { label: "L", nodeType: "action", config: {} },
  ...over,
} as WorkflowNodeSerialized);

describe("normalizeWorkflowNodes", () => {
  it("promotes a legacy action:ai_generate node to top-level ai_generate", () => {
    const [n] = normalizeWorkflowNodes([
      node({ type: "action", data: { label: "Gen", nodeType: "action", config: { actionType: "ai_generate" as never, aiPrompt: "x" } } }),
    ]);
    expect(n.type).toBe("ai_generate");
    expect(n.data.nodeType).toBe("ai_generate");
    // config (aiPrompt) preserved
    expect((n.data.config as { aiPrompt?: string }).aiPrompt).toBe("x");
  });

  it("promotes ai_classify/ai_extract/ai_decide too", () => {
    for (const at of ["ai_classify", "ai_extract", "ai_decide"]) {
      const [n] = normalizeWorkflowNodes([
        node({ data: { label: at, nodeType: "action", config: { actionType: at as never } } }),
      ]);
      expect(n.type).toBe(at);
      expect(n.data.nodeType).toBe(at);
    }
  });

  it("leaves non-AI actions (db_update, set_variable) as action nodes", () => {
    const nodes = normalizeWorkflowNodes([
      node({ data: { label: "U", nodeType: "action", config: { actionType: "db_update", table: "x" } } }),
      node({ data: { label: "S", nodeType: "action", config: { actionType: "set_variable", variableName: "v" } } }),
    ]);
    expect(nodes[0].type).toBe("action");
    expect(nodes[0].data.nodeType).toBe("action");
    expect(nodes[1].type).toBe("action");
  });

  it("leaves an already-canonical top-level ai_generate node untouched", () => {
    const [n] = normalizeWorkflowNodes([
      node({ type: "ai_generate", data: { label: "G", nodeType: "ai_generate", config: {} } }),
    ]);
    expect(n.type).toBe("ai_generate");
  });

  it("tolerates undefined/empty input", () => {
    expect(normalizeWorkflowNodes(undefined)).toEqual([]);
    expect(normalizeWorkflowNodes(null)).toEqual([]);
    expect(normalizeWorkflowNodes([])).toEqual([]);
  });
});
