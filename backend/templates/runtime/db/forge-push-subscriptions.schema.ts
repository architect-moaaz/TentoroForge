import { pgTable, uuid, text, timestamp } from "drizzle-orm/pg-core";

/**
 * Where a person's devices listen for the application's push notifications.
 * One row per browser subscription; `endpoint` is the push service's own
 * address for that device and is unique. The keys (`p256dh`, `auth`) encrypt
 * each message for that device alone — they are the device's, not the
 * person's password, and reach nobody but the push module.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgePushSubscriptions = pgTable("forge_push_subscriptions", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: text("user_id").notNull(),
  endpoint: text("endpoint").notNull().unique(),
  p256dh: text("p256dh").notNull(),
  auth: text("auth").notNull(),
  userAgent: text("user_agent"),
  createdAt: timestamp("created_at").defaultNow(),
});
