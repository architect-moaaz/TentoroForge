import type { TaskDTO } from "./types";

export interface TaskField {
  name: string;
  type: "string" | "number" | "boolean" | "select";
  required: boolean;
  options?: string[];
}

export type TaskFormSpec =
  | { kind: "approval"; fields: TaskField[] }
  | { kind: "fields"; fields: TaskField[] }
  | { kind: "json"; fields: TaskField[] };

export function taskFormSpec(task: TaskDTO): TaskFormSpec {
  // Every human node collapses to task_type "user_task" on the backend, so the
  // original workflow node type travels in input_data.node_type. An approval
  // node gets the approve/reject form regardless of task_type.
  const nodeType = task.input_data?.node_type as string | undefined;
  if (task.task_type === "approval" || nodeType === "approval") {
    return {
      kind: "approval",
      fields: [
        { name: "decision", type: "select", required: true, options: ["approved", "rejected"] },
        { name: "comment", type: "string", required: false },
      ],
    };
  }
  const declared = (task.input_data?.expectedOutputs as { name: string; type: string }[] | undefined) ?? null;
  if (declared && declared.length > 0) {
    return {
      kind: "fields",
      fields: declared.map((d) => ({
        name: d.name,
        type: (["string", "number", "boolean"].includes(d.type) ? d.type : "string") as TaskField["type"],
        required: false,
      })),
    };
  }
  return { kind: "json", fields: [] };
}

function coerce(type: TaskField["type"], raw: unknown): unknown {
  if (type === "number") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  if (type === "boolean") return raw === true || raw === "true";
  return raw;
}

export function buildTaskOutput(spec: TaskFormSpec, values: Record<string, unknown>): Record<string, unknown> {
  if (spec.kind === "json") {
    const raw = (values.__json as string) ?? "{}";
    try {
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }
  if (spec.kind === "approval") {
    const decision = values.decision as string;
    return { decision, approved: decision === "approved", comment: (values.comment as string) ?? "" };
  }
  const out: Record<string, unknown> = {};
  for (const f of spec.fields) {
    if (values[f.name] !== undefined && values[f.name] !== "") out[f.name] = coerce(f.type, values[f.name]);
  }
  return out;
}
