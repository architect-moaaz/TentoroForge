/** Drizzle schema for workflow engine tables (wf_ prefix to avoid collisions). */

import {
  pgTable,
  uuid,
  varchar,
  text,
  timestamp,
  jsonb,
  integer,
} from 'drizzle-orm/pg-core';
import { relations } from 'drizzle-orm';

// --- wf_instances ---

export const wfInstances = pgTable('wf_instances', {
  id: uuid('id').defaultRandom().primaryKey(),
  workflowId: varchar('workflow_id', { length: 255 }).notNull(),
  workflowName: varchar('workflow_name', { length: 255 }).notNull(),
  status: varchar('status', { length: 50 }).notNull().default('created'),
  currentNodeIds: jsonb('current_node_ids').$type<string[]>().default([]),
  variables: jsonb('variables').$type<Record<string, unknown>>().default({}),
  initiatedBy: varchar('initiated_by', { length: 255 }),
  errorMessage: text('error_message'),
  startedAt: timestamp('started_at', { withTimezone: true }),
  completedAt: timestamp('completed_at', { withTimezone: true }),
  createdAt: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).defaultNow().notNull(),
});

// --- wf_task_instances ---

export const wfTaskInstances = pgTable('wf_task_instances', {
  id: uuid('id').defaultRandom().primaryKey(),
  workflowInstanceId: uuid('workflow_instance_id')
    .notNull()
    .references(() => wfInstances.id, { onDelete: 'cascade' }),
  nodeId: varchar('node_id', { length: 255 }).notNull(),
  nodeLabel: varchar('node_label', { length: 255 }),
  taskType: varchar('task_type', { length: 50 }).notNull(),
  status: varchar('status', { length: 50 }).notNull().default('pending'),
  assigneeId: varchar('assignee_id', { length: 255 }),
  assigneeType: varchar('assignee_type', { length: 100 }),
  inputData: jsonb('input_data').$type<Record<string, unknown>>().default({}),
  outputData: jsonb('output_data').$type<Record<string, unknown>>().default({}),
  dueAt: timestamp('due_at', { withTimezone: true }),
  completedAt: timestamp('completed_at', { withTimezone: true }),
  errorMessage: text('error_message'),
  createdAt: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).defaultNow().notNull(),
});

// --- wf_execution_logs ---

export const wfExecutionLogs = pgTable('wf_execution_logs', {
  id: uuid('id').defaultRandom().primaryKey(),
  workflowInstanceId: uuid('workflow_instance_id')
    .notNull()
    .references(() => wfInstances.id, { onDelete: 'cascade' }),
  nodeId: varchar('node_id', { length: 255 }).notNull(),
  nodeType: varchar('node_type', { length: 100 }).notNull(),
  nodeLabel: varchar('node_label', { length: 255 }),
  status: varchar('status', { length: 50 }).notNull(),
  inputSnapshot: jsonb('input_snapshot').$type<Record<string, unknown>>(),
  outputSnapshot: jsonb('output_snapshot').$type<Record<string, unknown>>(),
  errorMessage: text('error_message'),
  startedAt: timestamp('started_at', { withTimezone: true }).notNull(),
  completedAt: timestamp('completed_at', { withTimezone: true }),
  durationMs: integer('duration_ms'),
});

// --- Relations ---

export const wfInstancesRelations = relations(wfInstances, ({ many }) => ({
  taskInstances: many(wfTaskInstances),
  executionLogs: many(wfExecutionLogs),
}));

export const wfTaskInstancesRelations = relations(wfTaskInstances, ({ one }) => ({
  workflowInstance: one(wfInstances, {
    fields: [wfTaskInstances.workflowInstanceId],
    references: [wfInstances.id],
  }),
}));

export const wfExecutionLogsRelations = relations(wfExecutionLogs, ({ one }) => ({
  workflowInstance: one(wfInstances, {
    fields: [wfExecutionLogs.workflowInstanceId],
    references: [wfInstances.id],
  }),
}));

// --- Inferred types ---

export type WfInstance = typeof wfInstances.$inferSelect;
export type NewWfInstance = typeof wfInstances.$inferInsert;
export type WfTaskInstance = typeof wfTaskInstances.$inferSelect;
export type NewWfTaskInstance = typeof wfTaskInstances.$inferInsert;
export type WfExecutionLog = typeof wfExecutionLogs.$inferSelect;
export type NewWfExecutionLog = typeof wfExecutionLogs.$inferInsert;
