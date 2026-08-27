import { pgTable, uuid, text, integer, jsonb, timestamp, index } from "drizzle-orm/pg-core";

/**
 * Per-node execution log written by the workflow engine.
 *
 * One row per node execution. Powers the "History" affordance in the
 * platform's workflow editor Properties panel (last N runs of the
 * currently-selected node, showing the resolved inputs and produced
 * outputs so the author can debug wiring problems without simulator
 * ceremony).
 *
 * Contract lives in
 *   docs/superpowers/specs/2026-07-22-workflow-node-contracts.md § NC-4.
 *
 * Row shape mirrors the ExecutionLogEntry runtime type but adds durable
 * fields (id, run_id, step_index, duration_ms). Written by the engine
 * inside handleAction (index.ts) — do not remove.
 */
export const forgeWorkflowExecutionLog = pgTable(
  "workflow_execution_log",
  {
    id: uuid("id").primaryKey().defaultRandom(),

    // Correlates every step of the same run. Independent from
    // workflow_instance_id so free-run (no persistence) also has a
    // grouping key.
    runId: text("run_id").notNull(),

    // Which workflow definition this row is for. text so it accepts
    // both the workflow's id and its slug.
    workflowId: text("workflow_id").notNull(),

    // The node inside the workflow (the id from the workflow JSON).
    nodeId: text("node_id").notNull(),
    nodeLabel: text("node_label").notNull().default(""),
    actionType: text("action_type").notNull().default(""),

    // Ordinal position of this step within the run.
    stepIndex: integer("step_index").notNull().default(0),

    // Fully-resolved inputs at exec time and the produced outputs.
    // outputs is nullable — a failing step's outputs are unknown.
    inputs: jsonb("inputs").notNull().default({}),
    outputs: jsonb("outputs"),

    // Terminal state + human-readable error if it failed.
    status: text("status").notNull().default("completed"), // running | completed | failed | skipped
    error: text("error"),

    durationMs: integer("duration_ms"),
    createdAt: timestamp("created_at").defaultNow(),
  },
  (t) => ({
    idxRun: index("wel_run_idx").on(t.runId, t.stepIndex),
    idxNode: index("wel_node_idx").on(t.workflowId, t.nodeId, t.createdAt),
  }),
);
