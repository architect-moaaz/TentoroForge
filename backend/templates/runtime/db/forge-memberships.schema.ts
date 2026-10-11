/**
 * forge_memberships — who belongs to which organisation, with what role.
 * The organisation itself is the application's tenant entity; this table
 * is the runtime's, like forge_invites. A person's active organisation is
 * `users.active_org_id`. Forge runtime — do not remove.
 */
import { index, pgTable, text, timestamp, uniqueIndex, uuid } from "drizzle-orm/pg-core";

export const forgeMemberships = pgTable("forge_memberships", {
  id: uuid("id").primaryKey().defaultRandom(),
  userId: text("user_id").notNull(),
  orgId: text("org_id").notNull(),
  role: text("role").notNull(),
  // active | removed
  status: text("status").notNull().default("active"),
  invitedBy: text("invited_by"),
  createdAt: timestamp("created_at").notNull().defaultNow(),
}, (t) => ({
  one: uniqueIndex("forge_memberships_user_org_idx").on(t.userId, t.orgId),
  byOrg: index("forge_memberships_org_idx").on(t.orgId),
}));
