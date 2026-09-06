import { describe, it, expect } from "vitest";
import { taskFormSpec, buildTaskOutput } from "./task-form";
import type { TaskDTO } from "./types";

function task(task_type: string, input_data: Record<string, unknown> | null = null): TaskDTO {
  return {
    id: "t1", node_id: "n1", node_label: "L", task_type, status: "pending",
    input_data, output_data: null,
  };
}

describe("taskFormSpec", () => {
  it("returns a decision + comment form for approval tasks", () => {
    const spec = taskFormSpec(task("approval"));
    expect(spec.kind).toBe("approval");
    expect(spec.fields.map((f) => f.name)).toEqual(["decision", "comment"]);
  });

  it("uses declared expectedOutputs from input_data when present", () => {
    const spec = taskFormSpec(task("user_task", { expectedOutputs: [{ name: "amount", type: "number" }] }));
    expect(spec.kind).toBe("fields");
    expect(spec.fields).toEqual([{ name: "amount", type: "number", required: false }]);
  });

  it("returns the approval form when the original node type is approval (backend collapses to user_task)", () => {
    const spec = taskFormSpec(task("user_task", { node_type: "approval" }));
    expect(spec.kind).toBe("approval");
    expect(spec.fields.map((f) => f.name)).toEqual(["decision", "comment"]);
  });

  it("renders typed fields from a node's form binding (expectedOutputs)", () => {
    const spec = taskFormSpec(task("user_task", {
      node_type: "user_task",
      expectedOutputs: [{ name: "visitNote", type: "string" }, { name: "weight", type: "number" }],
    }));
    expect(spec.kind).toBe("fields");
    expect(spec.fields.map((f) => f.name)).toEqual(["visitNote", "weight"]);
  });

  it("falls back to a raw JSON form only when nothing is declared", () => {
    const spec = taskFormSpec(task("user_task", { node_type: "user_task" }));
    expect(spec.kind).toBe("json");
  });
});

describe("buildTaskOutput", () => {
  it("maps approve/reject to a structured approval output", () => {
    expect(buildTaskOutput(taskFormSpec(task("approval")), { decision: "approved", comment: "ok" }))
      .toEqual({ decision: "approved", approved: true, comment: "ok" });
  });

  it("passes through field values for a fields form", () => {
    const spec = taskFormSpec(task("user_task", { expectedOutputs: [{ name: "amount", type: "number" }] }));
    expect(buildTaskOutput(spec, { amount: "42" })).toEqual({ amount: 42 });
  });

  it("parses raw JSON for a json form", () => {
    expect(buildTaskOutput(taskFormSpec(task("assignment")), { __json: '{"x":1}' })).toEqual({ x: 1 });
  });

  it("keeps non-numeric field values as-is (not NaN) when coercion fails", () => {
    const spec = taskFormSpec(task("user_task", { expectedOutputs: [{ name: "amount", type: "number" }] }));
    expect(buildTaskOutput(spec, { amount: "not-a-number" })).toEqual({ amount: "not-a-number" });
  });

  it("returns {} for malformed __json in a json form", () => {
    expect(buildTaskOutput(taskFormSpec(task("assignment")), { __json: '{bad json' })).toEqual({});
  });
});
