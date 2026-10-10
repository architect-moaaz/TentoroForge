import { pgTable, text, timestamp, uuid, index } from "drizzle-orm/pg-core";

/**
 * Conversations an AI agent handed to a person: who asked, why, how to reach them, the last of the
 * conversation, who has it and how it ended.
 *
 * Text ids, not foreign keys (like forge_notifications and forge_agent_conversations): the app's users table is the
 * app's, not the runtime's. Not exposed through /api/data (the file name starts with an underscore); the inbox
 * reads it through /api/agent/handoffs, which only lets the people who handle handoffs in.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeAgentHandoffs = pgTable(
  "forge_agent_handoffs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    /** Short and quotable: HO-7K3Q2A. */
    ref: text("ref").notNull(),
    conversationId: text("conversation_id").notNull(),
    agentId: text("agent_id").notNull(),
    requestedById: text("requested_by_id").notNull(),
    requestedByName: text("requested_by_name"),
    reason: text("reason").notNull(),
    // "low" | "normal" | "urgent"
    urgency: text("urgency").notNull().default("normal"),
    contact: text("contact"),
    summary: text("summary"),
    // "open" | "claimed" | "resolved"
    status: text("status").notNull().default("open"),
    assignedToId: text("assigned_to_id"),
    assignedToName: text("assigned_to_name"),
    resolutionNote: text("resolution_note"),
    createdAt: timestamp("created_at").notNull().defaultNow(),
    claimedAt: timestamp("claimed_at"),
    resolvedAt: timestamp("resolved_at"),
  },
  (t) => ({
    byConversation: index("idx_forge_agent_handoff_conv").on(t.conversationId),
    byStatus: index("idx_forge_agent_handoff_status").on(t.status, t.createdAt),
  }),
);
