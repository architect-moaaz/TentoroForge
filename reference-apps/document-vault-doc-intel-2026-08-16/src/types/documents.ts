import { documents } from "@/db/schema/documents";

export type Document = typeof documents.$inferSelect;
export type NewDocument = typeof documents.$inferInsert;
