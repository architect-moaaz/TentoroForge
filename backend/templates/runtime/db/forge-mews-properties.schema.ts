/**
 * forge_mews_properties — the hotels this application reaches in Mews, one
 * row per property, added and removed by the application's administrator
 * (/mews-properties). A property's access token is sealed (AES-256-GCM, the
 * app's SENSITIVE_ENCRYPTION_KEY) and only its mask is ever read back; the
 * runtime opens it inside a Mews call and nowhere else (`src/lib/mews.ts`).
 * A property with no token of its own is reached with the organisation's
 * portfolio token and its enterprise id. Forge runtime — do not remove.
 */
import { boolean, index, pgTable, text, timestamp, uuid } from "drizzle-orm/pg-core";

export const forgeMewsProperties = pgTable("forge_mews_properties", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: text("name").notNull(),
  // Mews's own id for the hotel (EnterpriseId); required with a portfolio token.
  enterpriseId: text("enterprise_id"),
  // demo | production — which Mews host the property's calls go to.
  environment: text("environment").notNull().default("demo"),
  accessTokenEncrypted: text("access_token_encrypted"),
  accessTokenMask: text("access_token_mask"),
  // What the last "Check connection" heard back from Mews.
  enterpriseName: text("enterprise_name"),
  checkedAt: timestamp("checked_at"),
  checkOk: boolean("check_ok"),
  checkMessage: text("check_message"),
  createdBy: text("created_by"),
  createdAt: timestamp("created_at").notNull().defaultNow(),
  updatedAt: timestamp("updated_at").notNull().defaultNow(),
}, (t) => ({
  byEnterprise: index("forge_mews_properties_enterprise_idx").on(t.enterpriseId),
}));
