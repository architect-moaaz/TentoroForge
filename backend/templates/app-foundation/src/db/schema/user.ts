// Default users table — required by auth.ts. Generated apps may extend
// or override per-project; this default keeps a fresh stamp-out compilable
// without forcing the schema agent to run before first build.
import { pgTable, text, boolean, timestamp, uuid } from "drizzle-orm/pg-core";

export const users = pgTable("users", {
  // uuid to match the id convention every generated entity uses — otherwise a
  // uuid FK column (e.g. assets.assigned_user_id) can't hold a serial user id
  // ("invalid input syntax for type uuid: 1"). The seed inserts no explicit id,
  // so defaultRandom() fills it; auth treats the id opaquely.
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  password: text("password").notNull(),
  name: text("name"),
  // The account type the user picked at signup (e.g. the Blueprint's
  // UserAccount.accountType). Nullable: apps whose signup offers no choice
  // never write it, and auth folds it into the session role when present so
  // the menu can gate on which kind of account signed up. Plain text, not a
  // DB enum — the value set is the app's, not the platform's.
  accountType: text("account_type"),
  isActive: boolean("is_active").default(true),
  createdAt: timestamp("created_at").defaultNow(),
});
