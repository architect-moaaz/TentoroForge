import { pgTable, uuid, text, jsonb, integer, timestamp, index, foreignKey } from "drizzle-orm/pg-core";

/**
 * What the app's AI agents say and remember — one conversation per person per
 * thread, its messages, and a rolling summary of the turns that no longer fit.
 *
 * `user_id` is text, not a foreign key (like forge_notifications): an agent may
 * answer a signed-out visitor ("anonymous"), and the app's users table is the
 * app's, not the runtime's. The chat route only ever reads a conversation back
 * for the person who started it.
 *
 * Not exposed through /api/data: the data route registers only schema files whose
 * name does not start with an underscore, and this one does. A conversation is
 * private to the person who had it.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeAgentConversations = pgTable(
  "forge_agent_conversations",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    agentId: text("agent_id").notNull(),
    userId: text("user_id").notNull(),
    // Folded form of the turns older than the replay window.
    summary: text("summary"),
    metadata: jsonb("metadata"),
    createdAt: timestamp("created_at").notNull().defaultNow(),
    updatedAt: timestamp("updated_at").notNull().defaultNow(),
  },
  (t) => ({ byUser: index("idx_forge_agent_conv_user").on(t.userId, t.updatedAt) }),
);

export const forgeAgentMessages = pgTable(
  "forge_agent_messages",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    conversationId: uuid("conversation_id").notNull(),
    // "user" | "assistant"
    role: text("role").notNull(),
    content: text("content").notNull(),
    // [{name, input, result|error}] — what the assistant's tools did this turn.
    toolCalls: jsonb("tool_calls"),
    tokenCount: integer("token_count"),
    createdAt: timestamp("created_at").notNull().defaultNow(),
  },
  (t) => ({
    byConversation: index("idx_forge_agent_msg_conv").on(t.conversationId, t.createdAt),
    // Named by hand: the name drizzle derives (table_column_reftable_refcolumn_fk) is
    // longer than Postgres's 63 characters, which truncates it, and a truncated name
    // never matches the one drizzle-kit expects — every later push would re-create it.
    conversation: foreignKey({
      name: "fk_forge_agent_msg_conv",
      columns: [t.conversationId],
      foreignColumns: [forgeAgentConversations.id],
    }).onDelete("cascade"),
  }),
);
