import { pgTable, uuid, text, boolean, timestamp } from "drizzle-orm/pg-core";

/**
 * In-app notifications raised by workflows (send_notification / fallback email).
 * Queryable at /api/notifications and displayable with ActivityFeed / Banner /
 * List. userId / entityId are text (not FK) so any workflow variable is safe to
 * store. Emitted by the Forge runtime — do not remove.
 */
export const forgeNotifications = pgTable("forge_notifications", {
  id: uuid("id").primaryKey().defaultRandom(),
  title: text("title").notNull(),
  message: text("message").notNull().default(""),
  userId: text("user_id"),
  role: text("role"),
  type: text("type").notNull().default("info"),
  entityId: text("entity_id"),
  read: boolean("read").notNull().default(false),
  createdAt: timestamp("created_at").defaultNow(),
});
