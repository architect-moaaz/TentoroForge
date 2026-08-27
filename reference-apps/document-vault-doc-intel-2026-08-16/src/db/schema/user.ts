// Users table — auth foundation base columns MERGED with the app's domain
// User columns (role, profile fields). Auth owns id/email/password; the
// deterministic schema builder appends the planner's columns. Single table.
import { pgTable, uuid, varchar, text, boolean, timestamp } from "drizzle-orm/pg-core";

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  password: text("password").notNull(),
  name: text("name"),
  isActive: boolean("is_active").default(true),
  createdAt: timestamp("created_at").defaultNow(),
  role: varchar("role", { length: 255 }),
});
