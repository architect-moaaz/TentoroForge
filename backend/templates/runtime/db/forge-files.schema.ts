import { pgTable, uuid, text, bigint, timestamp, customType } from "drizzle-orm/pg-core";

/** The file's bytes, when the app keeps them itself (`backend = "db"`). */
const bytea = customType<{ data: Buffer }>({ dataType: () => "bytea" });

/**
 * Uploaded-file metadata. Bytes live in the configured storage backend (local
 * disk by default, S3 when configured); this row is the addressable reference
 * used across forms and workflows. Emitted by the Forge runtime — do not remove.
 */
export const forgeFiles = pgTable("forge_files", {
  id: uuid("id").primaryKey().defaultRandom(),
  filename: text("filename").notNull(),
  contentType: text("content_type").notNull(),
  size: bigint("size", { mode: "number" }).notNull().default(0),
  backend: text("backend").notNull().default("local"),
  storageKey: text("storage_key").notNull(),
  uploadedById: uuid("uploaded_by_id"),
  createdAt: timestamp("created_at").defaultNow(),
  data: bytea("data"),
});
