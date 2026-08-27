import { pgTable, uuid, text, timestamp, boolean } from "drizzle-orm/pg-core";

/**
 * Last-run tracking for schedule-triggered workflows. /api/cron/tick reads this
 * to decide which scheduled workflows are due. Emitted by the Forge runtime.
 */
export const forgeSchedules = pgTable("forge_schedules", {
  id: uuid("id").primaryKey().defaultRandom(),
  workflowId: text("workflow_id").notNull().unique(),
  cadence: text("cadence").notNull().default("60m"),
  lastRunAt: timestamp("last_run_at"),
  enabled: boolean("enabled").notNull().default(true),
});
