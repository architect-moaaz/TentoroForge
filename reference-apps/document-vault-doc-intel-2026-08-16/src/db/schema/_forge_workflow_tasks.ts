import { pgTable, uuid, text, timestamp, jsonb } from "drizzle-orm/pg-core";

/**
 * Pending human tasks emitted by workflow user_task nodes.
 *
 * Every workflow that pauses on a user_task inserts one row here so
 * the assignee has something to open at /tasks. Written by
 * persistPendingTask in the runtime (workflows/index.ts) — column
 * shape mirrors the INSERT there. Lifecycle columns (completed_at,
 * completed_by, decision) are set by the task-completion path (Slice
 * E T2 detail page + resume).
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeWorkflowTasks = pgTable("workflow_tasks", {
  id: uuid("id").primaryKey().defaultRandom(),

  // Which workflow this task belongs to. text (not FK) so it accepts
  // both the workflow's id and its slug — the runtime looks up either.
  workflowId: text("workflow_id").notNull(),
  workflowInstanceId: uuid("workflow_instance_id").notNull().defaultRandom(),

  // The paused node that raised the task.
  nodeId: text("node_id").notNull().default(""),
  nodeLabel: text("node_label").notNull().default(""),
  taskType: text("task_type").notNull().default("user_task"),

  // Lifecycle state. pending | completed | cancelled | expired.
  status: text("status").notNull().default("pending"),

  // Assignment. Any one of the three may be non-null.
  assigneeId: text("assignee_id"),
  assigneeRole: text("assignee_role"),
  assigneeGroupId: text("assignee_group_id"),

  // The domain record this task acts on. Text so any workflow
  // variable is safe to store — no FK contract to break.
  entityType: text("entity_type").notNull().default(""),
  entityId: text("entity_id").notNull().default(""),

  // formData captures the record the workflow was invoked with;
  // formBinding names the form/component fields the user should
  // see; processVariables carries workflow-scoped state that the
  // resume path re-hydrates. All three are opaque JSON to the DB.
  formData: jsonb("form_data").notNull().default({}),
  formBinding: jsonb("form_binding").notNull().default({}),
  processVariables: jsonb("process_variables").notNull().default({}),

  // SLA + audit.
  dueAt: timestamp("due_at"),
  createdAt: timestamp("created_at").defaultNow(),

  // Completion audit — set by the resume path (Slice E T5).
  // decision is the user's choice ("approve" / "reject" / ...) —
  // whatever the workflow schema declares for that user_task.
  completedAt: timestamp("completed_at"),
  completedBy: text("completed_by"),
  decision: text("decision"),

  // Escalation policy picked up from the preceding `escalation` node
  // in the workflow graph (see engine.ts case "escalation" +
  // persistPendingTask). When due_at expires and the task is still
  // pending, processEscalations reassigns the task to `escalateTo`
  // (either a role name or a user id — same shape as assigneeRole).
  escalateTo: text("escalate_to"),
});
