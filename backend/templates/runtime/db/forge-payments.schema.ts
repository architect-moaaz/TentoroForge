/**
 * forge_payments — the application's own ledger of payments: one row per
 * checkout the application started, its provider's reference, what it was
 * for, and where it stands. The provider's signed event moves `status`;
 * nothing else does. Forge runtime — do not remove.
 */
import { index, integer, jsonb, pgTable, text, timestamp, uuid } from "drizzle-orm/pg-core";

export const forgePayments = pgTable("forge_payments", {
  id: uuid("id").primaryKey().defaultRandom(),
  provider: text("provider").notNull(),
  providerRef: text("provider_ref"),
  // pending | succeeded | failed | refunded | partially_refunded | cancelled
  status: text("status").notNull().default("pending"),
  amountMinor: integer("amount_minor").notNull(),
  currency: text("currency").notNull(),
  entity: text("entity"),
  entityId: text("entity_id"),
  actorId: text("actor_id"),
  description: text("description"),
  successUrl: text("success_url"),
  cancelUrl: text("cancel_url"),
  metadata: jsonb("metadata").notNull().default({}),
  createdAt: timestamp("created_at").notNull().defaultNow(),
  updatedAt: timestamp("updated_at").notNull().defaultNow(),
}, (t) => ({
  byRef: index("forge_payments_ref_idx").on(t.providerRef),
  byRecord: index("forge_payments_record_idx").on(t.entity, t.entityId),
}));
