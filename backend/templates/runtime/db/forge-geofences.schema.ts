import { pgTable, uuid, text, jsonb, boolean, doublePrecision, bigint, timestamp, primaryKey, uniqueIndex, index } from "drizzle-orm/pg-core";

/**
 * Geofencing: the zones, who they apply to, where each entity stands against each, and the crossings that happened.
 * The maths and the state machine are src/lib/geofence/engine.ts; this is where its results live.
 * Emitted by the Forge runtime — do not remove.
 */

/** A zone: a circle or a polygon, and how forgiving it is (see FenceRules in the engine). */
export const forgeGeofences = pgTable("forge_geofences", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: text("name").notNull(),
  /** { type: "circle", center: {lat,lng}, radiusM } | { type: "polygon", ring: [{lat,lng}, …] } */
  shape: jsonb("shape").notNull(),
  /** dwellSec, approachM, hysteresisM, minFixes, maxAccuracyM, staleMs, maxGapMs, enter, exit */
  rules: jsonb("rules").notNull().default({}),
  active: boolean("active").notNull().default(true),
  /** The record the zone belongs to, when it belongs to one: { entity: "Restaurant", id }. */
  owner: jsonb("owner"),
  orgId: text("org_id"),
  createdBy: text("created_by"),
  createdAt: timestamp("created_at").notNull().defaultNow(),
  updatedAt: timestamp("updated_at").notNull().defaultNow(),
});

/** Which entities a zone watches. A zone with no rows here watches every entity; subjectId "*" means every one of that type. */
export const forgeGeofenceAssignments = pgTable(
  "forge_geofence_assignments",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    geofenceId: uuid("geofence_id").notNull(),
    subjectType: text("subject_type").notNull(),
    subjectId: text("subject_id").notNull().default("*"),
    createdAt: timestamp("created_at").notNull().defaultNow(),
  },
  (t) => ({ unique: uniqueIndex("forge_geofence_assignments_unique").on(t.geofenceId, t.subjectType, t.subjectId) }),
);

/** Where one entity stands against one zone: the engine's State, kept between fixes. */
export const forgeGeofenceState = pgTable(
  "forge_geofence_state",
  {
    geofenceId: uuid("geofence_id").notNull(),
    entityType: text("entity_type").notNull(),
    entityId: text("entity_id").notNull(),
    phase: text("phase").notNull().default("outside"),
    state: jsonb("state").notNull(),
    updatedAt: timestamp("updated_at").notNull().defaultNow(),
  },
  (t) => ({
    pk: primaryKey({ columns: [t.geofenceId, t.entityType, t.entityId] }),
    inside: index("forge_geofence_state_inside_idx").on(t.entityType, t.entityId, t.phase),
  }),
);

/** One crossing. The id is the engine's own (the same crossing, the same id), so a repeated fix cannot record it twice. */
export const forgeGeofenceEvents = pgTable(
  "forge_geofence_events",
  {
    id: text("id").primaryKey(),
    type: text("type").notNull(),
    geofenceId: uuid("geofence_id").notNull(),
    entityType: text("entity_type").notNull(),
    entityId: text("entity_id").notNull(),
    lat: doublePrecision("lat").notNull(),
    lng: doublePrecision("lng").notNull(),
    occurredAt: bigint("occurred_at", { mode: "number" }).notNull(),
    detectedAt: bigint("detected_at", { mode: "number" }).notNull(),
    metadata: jsonb("metadata").notNull().default({}),
    createdAt: timestamp("created_at").notNull().defaultNow(),
  },
  (t) => ({
    byFence: index("forge_geofence_events_fence_idx").on(t.geofenceId, t.occurredAt),
    byEntity: index("forge_geofence_events_entity_idx").on(t.entityType, t.entityId, t.occurredAt),
  }),
);

/** "When this happens at this zone, do this" — worked through by the rules step (see lib/geofence/rules). */
export const forgeGeofenceRules = pgTable("forge_geofence_rules", {
  id: uuid("id").primaryKey().defaultRandom(),
  /** null = any zone */
  geofenceId: uuid("geofence_id"),
  /** "geofence.entered" | "geofence.exited" | "geofence.dwell" | "geofence.approaching" */
  onEvent: text("on_event").notNull(),
  /** An expression over the event and the entity; null = always. */
  condition: text("condition"),
  /** { kind: "emit_event" | "notify" | "workflow" | "update", … } */
  action: jsonb("action").notNull(),
  /** A crossing is only proximity. An action that moves money or finishes a job must be confirmed another way first. */
  sensitive: boolean("sensitive").notNull().default(false),
  /** The evidence that is not GPS: { event: "order.code_verified", withinSec? }. A sensitive rule without it never runs. */
  confirm: jsonb("confirm"),
  active: boolean("active").notNull().default(true),
  createdAt: timestamp("created_at").notNull().defaultNow(),
});
