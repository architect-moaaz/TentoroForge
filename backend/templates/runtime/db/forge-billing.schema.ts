/**
 * forge_subscriptions — each person's subscription to one of the app's plans:
 * the gateway it began on (it stays there), the gateway's own reference, and
 * what the gateway last said about it (status, the end of the paid period,
 * whether it ends there). The gateway is the truth; this row follows it.
 *
 * forge_plan_refs — a plan's id at a gateway, made once and reused: the same
 * plan at the same price is one plan at the gateway however many times the
 * app is deployed. Forge runtime — do not remove.
 */
import { bigint, boolean, index, jsonb, pgTable, text, timestamp, uuid } from "drizzle-orm/pg-core";

export const forgeSubscriptions = pgTable("forge_subscriptions", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: text("user_id").notNull(),
  planId: text("plan_id").notNull(),
  provider: text("provider").notNull(),
  providerRef: text("provider_ref"),
  // incomplete | trialing | active | past_due | paused | cancelled | expired
  status: text("status").notNull().default("incomplete"),
  currency: text("currency").notNull(),
  // bigint: IDR 25,000,000 is 2.5e9 in minor units, past a 32-bit integer.
  amountMinor: bigint("amount_minor", { mode: "number" }).notNull(),
  interval: text("interval").notNull(),
  currentPeriodEnd: timestamp("current_period_end", { withTimezone: true }),
  cancelAtPeriodEnd: boolean("cancel_at_period_end").notNull().default(false),
  customerRef: text("customer_ref"),
  checkedAt: timestamp("checked_at", { withTimezone: true }),
  metadata: jsonb("metadata").notNull().default({}),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t) => ({
  byUser: index("forge_subscriptions_user_idx").on(t.userId),
  byRef: index("forge_subscriptions_ref_idx").on(t.providerRef),
}));

export const forgePlanRefs = pgTable("forge_plan_refs", {
  key: text("key").primaryKey(),
  provider: text("provider").notNull(),
  ref: text("ref").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});
