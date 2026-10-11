/**
 * forge_audit — the trail. One row per thing that happened to a record:
 * who, when, what, before and after; sensitive reads, exports and sign-ins
 * when the level is `regulated`. Tamper-evident (each row carries the hash
 * of the previous row's hash and its own facts) and immutable (a trigger
 * refuses UPDATE, DELETE and TRUNCATE; retention goes through one function
 * that writes a `prune` row carrying the range it removed).
 *
 * Forge runtime — do not remove.
 */
import { bigserial, index, jsonb, pgTable, text, timestamp, uuid } from "drizzle-orm/pg-core";

export const forgeAudit = pgTable("forge_audit", {
  id: uuid("id").primaryKey().defaultRandom(),
  seq: bigserial("seq", { mode: "number" }).notNull(),
  at: timestamp("at", { withTimezone: true }).notNull().defaultNow(),
  actorId: text("actor_id"),
  actorRole: text("actor_role"),
  actorOrgId: text("actor_org_id"),
  // user | guest | system | workflow | event
  actorKind: text("actor_kind").notNull().default("user"),
  // api | workflow:<id> | event:<type> | seed | smith
  via: text("via").notNull().default("api"),
  runId: text("run_id"),
  // create | update | delete | read_sensitive | export | login | login_failed |
  // invite | role_change | org_switch | prune
  action: text("action").notNull(),
  entity: text("entity").notNull(),
  entityId: text("entity_id"),
  before: jsonb("before"),
  after: jsonb("after"),
  changed: text("changed").array(),
  reason: text("reason"),
  requestId: text("request_id"),
  ip: text("ip"),
  userAgent: text("user_agent"),
  prevHash: text("prev_hash"),
  hash: text("hash"),
}, (t) => ({
  byRecord: index("forge_audit_record_idx").on(t.entity, t.entityId),
  byActor: index("forge_audit_actor_idx").on(t.actorId, t.at),
  byTime: index("forge_audit_at_idx").on(t.at),
}));
