import { pgTable, uuid, text, jsonb, timestamp } from "drizzle-orm/pg-core";

/**
 * Durable event bus rows — the "when X happens, do Y" substrate.
 *
 * emitEvent() (src/lib/events/bus.ts) inserts one row per domain event
 * ("order.created", "invoice.paid", …). processPendingEvents() claims
 * unprocessed rows and dispatches every workflow whose top-level
 * `trigger: {kind:"event", event}` matches, plus resumes any execution
 * paused on a wait_for_event node awaiting that event.
 *
 * Processing runs inline after emit (fire-and-forget) AND from the
 * /api/cron/tick sweeper, so a crashed inline pass is retried — rows are
 * claimed with FOR UPDATE SKIP LOCKED so concurrent invocations never
 * double-dispatch.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeEvents = pgTable("forge_events", {
  id: uuid("id").primaryKey().defaultRandom(),

  // Event type, dot-namespaced: "<entitySlug>.created|updated|deleted"
  // for data-engine events, or any custom name from an emit_event node.
  type: text("type").notNull(),

  // The entity slug the event concerns (nullable — custom events may
  // not be about an entity at all).
  entity: text("entity"),
  entityId: text("entity_id"),

  // Opaque event payload (the record, previous record, acting user, …).
  payload: jsonb("payload").notNull().default({}),

  createdAt: timestamp("created_at").notNull().defaultNow(),

  // NULL until claimed by processPendingEvents. The claim UPDATE sets it
  // atomically, so a row is dispatched at most once.
  processedAt: timestamp("processed_at"),

  // Dispatch failure message, if any (row stays processed — the error is
  // for observability, not retry bookkeeping).
  error: text("error"),
});
