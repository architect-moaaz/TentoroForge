import { pgTable, text, integer, timestamp, primaryKey } from "drizzle-orm/pg-core";

/**
 * How much each person has used the app's AI assistants, one row per person per minute: what the usage limits
 * (messages per minute and hour, tokens per day) are checked against. `user_id` is text, like the conversation
 * tables: it is not a foreign key into the app's own users table.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeAgentUsage = pgTable(
  "forge_agent_usage",
  {
    userId: text("user_id").notNull(),
    bucket: timestamp("bucket").notNull(),
    messages: integer("messages").notNull().default(0),
    tokens: integer("tokens").notNull().default(0),
  },
  (t) => ({ pk: primaryKey({ columns: [t.userId, t.bucket] }) }),
);
