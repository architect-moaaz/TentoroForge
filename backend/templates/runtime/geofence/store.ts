/**
 * The geofence store on Postgres. Raw SQL on purpose (like the event bus): `ON CONFLICT` and one round trip per step.
 * Every method may throw when the tables are missing (an app made before geofencing); the caller treats that as "no zones".
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { sql } from "drizzle-orm";
import type { Fence, GeofenceEvent, State } from "./engine";
import type { GeofenceStore, Subject } from "./service";
import type { Held, Rule } from "./rules";
import { coarsen, coordDecimals, cutoffMs, retentionDays } from "./privacy";

function rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}
const json = (v: unknown) => (typeof v === "string" ? JSON.parse(v) : v);
const uuids = (ids: string[]) => sql.join(ids.map((i) => sql`${i}::uuid`), sql`, `);

export async function loadRules(): Promise<Rule[]> {
  const res = await db.execute(sql`SELECT id, geofence_id, on_event, condition, action, sensitive, confirm, active FROM forge_geofence_rules WHERE active = true ORDER BY created_at`);
  return rows(res).map((r): Rule => ({
    id: String(r.id), geofenceId: r.geofence_id ? String(r.geofence_id) : null, onEvent: String(r.on_event),
    condition: r.condition ?? null, action: json(r.action), sensitive: !!r.sensitive, confirm: r.confirm ? json(r.confirm) : null, active: r.active !== false,
  }));
}

/** Was an event of this type recorded on the bus for this entity (not older than `sinceMs`, an epoch time)? */
export async function hasEvidence(entityType: string, entityId: string, eventType: string, sinceMs: number | null): Promise<boolean> {
  const res = await db.execute(sql`
    SELECT 1 FROM forge_events
    WHERE type = ${eventType} AND lower(entity) = lower(${entityType}) AND entity_id = ${entityId}
      AND (${sinceMs}::bigint IS NULL OR created_at >= to_timestamp(${sinceMs}::bigint / 1000.0))
    LIMIT 1`);
  return rows(res).length > 0;
}

/** Held actions of this entity whose rule waits for `confirmEvent`, with the crossing each came from. */
export async function heldFor(entityType: string, entityId: string, confirmEvent: string): Promise<Held[]> {
  const held = rows(await db.execute(sql`
    SELECT payload->>'ruleId' AS rule_id, payload->>'geofenceEvent' AS event_id, created_at
    FROM forge_events
    WHERE type = 'geofence.action_held' AND lower(entity) = lower(${entityType}) AND entity_id = ${entityId}
      AND created_at > NOW() - INTERVAL '24 hours'`));
  if (!held.length) return [];
  const rules = (await loadRules()).filter((r) => r.confirm?.event === confirmEvent);
  const out: Held[] = [];
  for (const h of held) {
    const rule = rules.find((r) => r.id === h.rule_id);
    if (!rule) continue;
    const ev = rows(await db.execute(sql`
      SELECT id, type, geofence_id, entity_type, entity_id, lat, lng, occurred_at, detected_at, metadata FROM forge_geofence_events WHERE id = ${h.event_id}`))[0];
    if (!ev) continue;
    out.push({ rule, heldAt: new Date(h.created_at).getTime(), event: asEvent(ev) });
  }
  return out;
}

function asEvent(ev: any): GeofenceEvent {
  return {
    id: ev.id, type: ev.type, geofenceId: String(ev.geofence_id), entityType: ev.entity_type, entityId: ev.entity_id,
    lat: ev.lat, lng: ev.lng, occurredAt: Number(ev.occurred_at), detectedAt: Number(ev.detected_at), metadata: json(ev.metadata) ?? {},
  };
}

/** The latest crossings for these entities of one kind, oldest first, for a monitor that has just opened. */
export async function recentEvents(entityType: string, entityIds: string[], limit = 50): Promise<GeofenceEvent[]> {
  if (!entityIds.length) return [];
  const list = sql.join(entityIds.slice(0, 500).map((i) => sql`${i}`), sql`, `);
  const res = await db.execute(sql`
    SELECT id, type, geofence_id, entity_type, entity_id, lat, lng, occurred_at, detected_at, metadata
    FROM forge_geofence_events
    WHERE lower(entity_type) = lower(${entityType}) AND entity_id IN (${list})
    ORDER BY occurred_at DESC LIMIT ${limit}`);
  return rows(res).reverse().map(asEvent);
}

export const postgresGeofenceStore: GeofenceStore = {
  async loadFences() {
    const res = await db.execute(sql`SELECT id, shape, rules, active FROM forge_geofences WHERE active = true`);
    return rows(res).map((r): Fence => ({ id: String(r.id), shape: json(r.shape), rules: json(r.rules) ?? {}, active: r.active !== false }));
  },

  async loadAssignments() {
    const res = await db.execute(sql`SELECT geofence_id, subject_type, subject_id FROM forge_geofence_assignments`);
    const out = new Map<string, string[]>();
    for (const r of rows(res)) {
      const k = String(r.geofence_id);
      (out.get(k) ?? out.set(k, []).get(k)!).push(`${r.subject_type}:${r.subject_id}`);
    }
    return out;
  },

  async insideFenceIds(who: Subject) {
    const res = await db.execute(sql`
      SELECT geofence_id FROM forge_geofence_state
      WHERE entity_type = ${who.entityType} AND entity_id = ${who.entityId} AND phase = 'inside'`);
    return rows(res).map((r) => String(r.geofence_id));
  },

  async loadStates(who: Subject, ids: string[]) {
    const out = new Map<string, State>();
    if (!ids.length) return out;
    const res = await db.execute(sql`
      SELECT geofence_id, state FROM forge_geofence_state
      WHERE entity_type = ${who.entityType} AND entity_id = ${who.entityId} AND geofence_id IN (${uuids(ids)})`);
    for (const r of rows(res)) out.set(String(r.geofence_id), json(r.state) as State);
    return out;
  },

  async saveStates(who: Subject, states: Map<string, State>) {
    for (const [fenceId, s] of states) {
      await db.execute(sql`
        INSERT INTO forge_geofence_state (geofence_id, entity_type, entity_id, phase, state, updated_at)
        VALUES (${fenceId}::uuid, ${who.entityType}, ${who.entityId}, ${s.phase}, ${JSON.stringify(s)}::jsonb, NOW())
        ON CONFLICT (geofence_id, entity_type, entity_id)
        DO UPDATE SET phase = EXCLUDED.phase, state = EXCLUDED.state, updated_at = NOW()`);
    }
  },

  async recordEvents(events: GeofenceEvent[]) {
    const fresh: GeofenceEvent[] = [];
    const dp = coordDecimals();
    for (const e of events) {
      const res = await db.execute(sql`
        INSERT INTO forge_geofence_events (id, type, geofence_id, entity_type, entity_id, lat, lng, occurred_at, detected_at, metadata, created_at)
        VALUES (${e.id}, ${e.type}, ${e.geofenceId}::uuid, ${e.entityType}, ${e.entityId}, ${coarsen(e.lat, dp)}, ${coarsen(e.lng, dp)}, ${e.occurredAt}, ${e.detectedAt}, ${JSON.stringify(e.metadata)}::jsonb, NOW())
        ON CONFLICT (id) DO NOTHING
        RETURNING id`);
      if (rows(res).length) fresh.push(e);
    }
    return fresh;
  },
};

/** Delete what is older than the retention period (FORGE_GEOFENCE_RETENTION_DAYS). Where a person stands NOW is not history: only the state of someone outside the zone is dropped. */
export async function purgeOld(now = Date.now(), days = retentionDays()): Promise<{ events: number; states: number }> {
  const cut = cutoffMs(now, days);
  if (cut == null) return { events: 0, states: 0 };
  const ev = rows(await db.execute(sql`DELETE FROM forge_geofence_events WHERE occurred_at < ${cut} RETURNING id`));
  const st = rows(await db.execute(sql`DELETE FROM forge_geofence_state WHERE phase = 'outside' AND updated_at < to_timestamp(${cut} / 1000.0) RETURNING entity_id`));
  await dropBusCopies(sql`created_at < to_timestamp(${cut} / 1000.0)`);
  return { events: ev.length, states: st.length };
}

/** Every crossing is also announced on the event bus with its exact position (`announce`); that copy is history too, so what
 *  is purged or erased here goes from there as well. Best effort: an app whose bus table is missing has no copy to drop. */
async function dropBusCopies(where: ReturnType<typeof sql>): Promise<void> {
  try {
    await db.execute(sql`DELETE FROM forge_events WHERE type LIKE 'geofence.%' AND ${where}`);
  } catch { /* no bus table, nothing kept there */ }
}

/** Forget one record entirely: its crossings and where it stood against every zone (a person leaves, a customer asks to be erased). */
export async function eraseEntity(entityType: string, entityId: string): Promise<{ events: number; states: number }> {
  const ev = rows(await db.execute(sql`DELETE FROM forge_geofence_events WHERE lower(entity_type) = lower(${entityType}) AND entity_id = ${entityId} RETURNING id`));
  const st = rows(await db.execute(sql`DELETE FROM forge_geofence_state WHERE lower(entity_type) = lower(${entityType}) AND entity_id = ${entityId} RETURNING entity_id`));
  await dropBusCopies(sql`entity_id = ${entityId}`);
  return { events: ev.length, states: st.length };
}
