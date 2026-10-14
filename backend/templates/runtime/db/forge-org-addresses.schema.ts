/**
 * forge_org_addresses — the address each organisation answers at, as
 * `<slug>.<FORGE_ORG_DOMAIN>`. Given from the organisation's name when first
 * needed; changed by its admin. Forge runtime — do not remove.
 */
import { pgTable, text, timestamp, uniqueIndex } from "drizzle-orm/pg-core";

export const forgeOrgAddresses = pgTable("forge_org_addresses", {
  orgId: text("org_id").primaryKey(),
  slug: text("slug").notNull(),
  updatedAt: timestamp("updated_at").notNull().defaultNow(),
}, (t) => ({
  bySlug: uniqueIndex("forge_org_addresses_slug_idx").on(t.slug),
}));
