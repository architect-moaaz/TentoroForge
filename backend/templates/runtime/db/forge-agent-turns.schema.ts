import { pgTable, text, integer, boolean, jsonb, timestamp, uuid, index } from "drizzle-orm/pg-core";

/**
 * One row per assistant TURN (one message the person sent and the answer it got): which agent and model, what it cost
 * in tokens, how long it took, how it ended, which tools it used and whether they worked, and the person's thumbs up
 * or down. It is what the builder's cost-and-quality view is drawn from.
 *
 * It holds NO message text and no tool results: the words live in forge_agent_messages. The one exception is
 * `problem_message`, which stays empty unless the builder switched FORGE_INSIGHTS_INCLUDE_TEXT on, and then holds the
 * first 200 characters of what the person wrote, for a turn that went wrong. Text ids, not foreign keys (like the
 * other forge agent tables): the app's users table is the app's, not the runtime's. Not exposed through /api/data
 * (the file name starts with an underscore).
 *
 * THIS TABLE IS ALSO THE OUTBOX of the platform's insights (agents/insights-shipper.ts). A row is "waiting to be
 * sent" while `shipped_at` is empty. The row's `id` is the turn's event id on the platform, which keeps the first
 * copy and ignores the rest, so sending a row twice (after a crash, say) never counts it twice. Rows that were sent
 * are deleted a week later by the cron tick (agents/insights-outbox.ts); an app that never sends keeps all its rows.
 *
 * Recording is best-effort: an app updated but not yet migrated simply has no rows until the database is pushed.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeAgentTurns = pgTable(
  "forge_agent_turns",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    // Empty when the message was refused before any conversation existed.
    conversationId: text("conversation_id").notNull(),
    agentId: text("agent_id").notNull(),
    userId: text("user_id").notNull(),
    // The person's role name when they were signed in ("Admin"), else empty. Sent with the turn so the platform can
    // split the numbers by role; the person themselves is only ever sent as a salted hash (see insights-shipper.ts).
    userRole: text("user_role"),
    // The model that actually answered (the one the provider reports), not just the one asked for.
    model: text("model"),
    inputTokens: integer("input_tokens").default(0),
    outputTokens: integer("output_tokens").default(0),
    // Wall time of the whole turn, in milliseconds.
    ms: integer("ms").default(0),
    // "ok" | "error" | "blocked"
    status: text("status").notNull(),
    // Why it failed or was blocked: a short sentence.
    error: text("error"),
    toolCalls: integer("tool_calls").default(0),
    toolErrors: integer("tool_errors").default(0),
    // [{name, ok, ms}] — at most 20.
    toolStats: jsonb("tool_stats"),
    handedOff: boolean("handed_off").default(false),
    // The assistant message this turn saved: what a thumbs up or down is matched to.
    assistantMessageId: text("assistant_message_id"),
    // 1 = the first message of its conversation. Empty on rows written before this column existed.
    turnNumber: integer("turn_number"),
    // 1 (good) | -1 (bad) | null (not rated)
    rating: integer("rating"),
    ratingNote: text("rating_note"),
    // When the rating last changed. A rating that changes after the turn was sent puts the row back in the outbox.
    ratingAt: timestamp("rating_at"),
    // What the person wrote, for a turn that went wrong — ONLY when FORGE_INSIGHTS_INCLUDE_TEXT=1 (see above).
    problemMessage: text("problem_message"),
    createdAt: timestamp("created_at").defaultNow(),
    // The outbox. `shipped_at` empty = still to send. Set when the platform took it, and also when the platform
    // refused it for good (then `ship_error` says why), so a row that can never be accepted is not tried forever.
    shippedAt: timestamp("shipped_at"),
    // How many times sending it failed for a reason worth retrying (platform down, rate limited, no network).
    shipAttempts: integer("ship_attempts").default(0),
    // The last thing that went wrong with it, in a few words. Empty when all is well.
    shipError: text("ship_error"),
  },
  (t) => ({
    byTime: index("idx_forge_agent_turns_time").on(t.createdAt),
    byAgent: index("idx_forge_agent_turns_agent").on(t.agentId, t.createdAt),
    byMessage: index("idx_forge_agent_turns_msg").on(t.assistantMessageId),
    // "The oldest rows still to send" and "rows sent more than a week ago": both walk this one index in order.
    byShipped: index("idx_forge_agent_turns_shipped").on(t.shippedAt, t.createdAt),
  }),
);
