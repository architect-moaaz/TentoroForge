/**
 * forge_mews_stays — the recent stays of the hotels this application reaches
 * in Mews, kept so a desk typing part of a guest's name is answered at once
 * (`suggestStays` in src/lib/mews.ts). One row per Mews reservation, with its
 * guest, room, dates and charged payment; refreshed with what Mews changed
 * (`syncStays`, from the cron tick). forge_mews_sync records how far each
 * connection's sync has got. Forge runtime — do not remove.
 */
import { integer, jsonb, pgTable, text, timestamp } from "drizzle-orm/pg-core";

export const forgeMewsStays = pgTable("forge_mews_stays", {
  reservationId: text("reservation_id").primaryKey(),
  // A property's id in forge_mews_properties, or "organisation".
  connection: text("connection").notNull(),
  confirmationNumber: text("confirmation_number"),
  state: text("state"),
  arrivalDate: text("arrival_date"),
  departureDate: text("departure_date"),
  customerId: text("customer_id"),
  accountId: text("account_id"),
  guestName: text("guest_name"),
  guestEmail: text("guest_email"),
  roomNumber: text("room_number"),
  billId: text("bill_id"),
  payment: jsonb("payment"),
  updatedUtc: timestamp("updated_utc"),
  syncedAt: timestamp("synced_at").notNull().defaultNow(),
});

export const forgeMewsSync = pgTable("forge_mews_sync", {
  connection: text("connection").primaryKey(),
  // Everything Mews changed before this has been kept.
  syncedThrough: timestamp("synced_through"),
  lastRunAt: timestamp("last_run_at"),
  lastError: text("last_error"),
  stays: integer("stays").notNull().default(0),
});
