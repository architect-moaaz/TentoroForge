import { pgTable, uuid, text, timestamp } from "drizzle-orm/pg-core";

/**
 * A person's tokens for connecting an AI assistant (`lib/mcp/tokens.ts`).
 * Only the SHA-256 digest of a token is kept, with its last four characters.
 *
 * DECLARED, NOT ONLY CREATED. The table was made on first use and nothing in
 * the schema named it, so the schema push (`drizzle-kit push --force`, on
 * every publish and every change to the records) dropped it as unknown — and
 * with it every token anyone had made.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeMcpTokens = pgTable("_forge_mcp_tokens", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: text("user_id").notNull(),
  label: text("label").notNull().default(""),
  tokenHash: text("token_hash").notNull().unique(),
  last4: text("last4").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  lastUsedAt: timestamp("last_used_at", { withTimezone: true }),
  revokedAt: timestamp("revoked_at", { withTimezone: true }),
});
