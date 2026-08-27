import { pgTable, uuid, varchar, text, integer, real, timestamp, jsonb } from "drizzle-orm/pg-core";
import { users } from "./user";

export const documents = pgTable("documents", {
  id: uuid("id").primaryKey().defaultRandom(),
  originalFilename: varchar("original_filename", { length: 255 }),
  fileUrl: varchar("file_url", { length: 255 }),
  mimeType: varchar("mime_type", { length: 255 }),
  fileSizeBytes: integer("file_size_bytes"),
  status: varchar("status", { length: 255 }),
  ocrText: text("ocr_text"),
  extractedFields: jsonb("extracted_fields"),
  confidence: real("confidence"),
  pageCount: integer("page_count"),
  uploadedBy: uuid("uploaded_by").references(() => users.id),
  uploadedByName: varchar("uploaded_by_name", { length: 255 }),
  processedAt: timestamp("processed_at"),
  errorMessage: text("error_message"),
  createdAt: timestamp("created_at"),
  updatedAt: timestamp("updated_at"),
});
