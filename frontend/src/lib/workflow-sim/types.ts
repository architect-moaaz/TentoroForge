// frontend/src/lib/workflow-sim/types.ts
export type LogStatus = "started" | "completed" | "failed" | "skipped";

export interface WorkflowInstanceDTO {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: "created" | "running" | "waiting" | "completed" | "failed" | "cancelled";
  current_node_ids: string[] | null;
  variables: Record<string, unknown> | null;
  error_message: string | null;
}

export interface TaskDTO {
  id: string;
  node_id: string;
  node_label: string | null;
  task_type: string;
  status: string; // pending | assigned | active | completed | ...
  input_data: Record<string, unknown> | null;
  output_data: Record<string, unknown> | null;
}

export interface InstanceDetailDTO extends WorkflowInstanceDTO {
  tasks: TaskDTO[];
}

export interface NodeLogDTO {
  id: string;
  node_id: string;
  node_type: string;
  node_label: string | null;
  status: LogStatus;
  output_snapshot: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

/** Visual status painted on each node in the canvas overlay. */
export type NodeVisualStatus = "pending" | "active" | "done" | "failed";

/** High-level state of a simulator run. */
export type RunPhase =
  | "idle"
  | "starting"
  | "running"
  | "awaitingInput"
  | "completed"
  | "failed"
  | "cancelled";
