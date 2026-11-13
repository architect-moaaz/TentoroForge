import { pgTable, uuid, text, timestamp } from "drizzle-orm/pg-core";

/**
 * Where a person's PHONES listen for the application's alerts: the Expo push token each installed copy of the native app
 * was given. One row per phone; `token` is unique, so a phone that signs in as someone else moves to them instead of
 * alerting both. The token is only an address — it can send nothing to anyone but that phone, and only through Expo.
 *
 * Emitted by the Forge runtime — do not remove.
 */
export const forgeDeviceTokens = pgTable("forge_device_tokens", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: text("user_id").notNull(),
  token: text("token").notNull().unique(),
  platform: text("platform"),
  createdAt: timestamp("created_at").defaultNow(),
  updatedAt: timestamp("updated_at").defaultNow(),
});
