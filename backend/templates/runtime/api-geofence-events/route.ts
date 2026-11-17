/**
 * GET /api/geofence/events?entity=Order[&id=<record>][&zone=<zone id>][&limit=50] — the history of crossings, newest first.
 *
 * Only crossings about records the app's own read rules let THIS person open (the same rule as the live line and the fleet
 * map). `id` narrows to one record; `zone` to one zone. Zone names come with the answer so a screen need not look them up.
 *
 * DELETE /api/geofence/events?entity=Order&id=<record> — forget one record's crossings and zone state (a zone manager only).
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { sql } from "drizzle-orm";
import { visibleIds, whoIs } from "@/lib/tracking/access";
import { refuse, who } from "@/lib/geofence/access";
import { eraseEntity } from "@/lib/geofence/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const rowsOf = (r: unknown): any[] => (Array.isArray(r) ? r : ((r as { rows?: any[] })?.rows ?? []));
const json = (v: unknown) => (typeof v === "string" ? JSON.parse(v) : v);
const UUID = /^[0-9a-f-]{36}$/i;

export async function GET(req: Request): Promise<Response> {
  const q = new URL(req.url).searchParams;
  const entity = q.get("entity")?.trim() ?? "";
  const id = q.get("id")?.trim() || null;
  const zone = q.get("zone")?.trim() || null;
  const limit = Math.min(Math.max(Number(q.get("limit") ?? 50) || 50, 1), 500);
  if (!(await whoIs())) return refuse(401, "Sign in to see the zones.");
  if (!entity) return refuse(400, "entity is required.");
  if (zone && !UUID.test(zone)) return refuse(400, "zone is not a zone id.");
  const seen = await visibleIds(entity);
  if (!seen.ok) return refuse(seen.status, seen.error);
  const ids = id ? (seen.ids.has(id) ? [id] : []) : [...seen.ids].slice(0, 500);
  if (!ids.length) return Response.json({ ok: true, events: [] });
  try {
    const list = sql.join(ids.map((i) => sql`${i}`), sql`, `);
    const rows = rowsOf(await db.execute(sql`
      SELECT e.id, e.type, e.geofence_id, z.name AS zone_name, e.entity_type, e.entity_id, e.lat, e.lng, e.occurred_at, e.detected_at, e.metadata
      FROM forge_geofence_events e LEFT JOIN forge_geofences z ON z.id = e.geofence_id
      WHERE lower(e.entity_type) = lower(${entity}) AND e.entity_id IN (${list})
        ${zone ? sql`AND e.geofence_id = ${zone}::uuid` : sql``}
      ORDER BY e.occurred_at DESC LIMIT ${limit}`));
    return Response.json({
      ok: true,
      events: rows.map((e) => ({
        id: e.id, type: e.type, geofenceId: String(e.geofence_id), zoneName: e.zone_name ?? null, entityType: e.entity_type, entityId: e.entity_id,
        lat: e.lat, lng: e.lng, occurredAt: Number(e.occurred_at), detectedAt: Number(e.detected_at), metadata: json(e.metadata) ?? {},
      })),
    });
  } catch {
    return Response.json({ ok: true, events: [] }); // an app with no geofence tables has no history
  }
}

export async function DELETE(req: Request): Promise<Response> {
  const q = new URL(req.url).searchParams;
  const entity = q.get("entity")?.trim() ?? "";
  const id = q.get("id")?.trim() ?? "";
  const me = await who();
  if (!me.ok) return refuse(me.status, me.error);
  if (!me.manager) return refuse(403, "Only a zone manager may erase a record's crossings.");
  if (!entity || !id) return refuse(400, "entity and id are both required.");
  try {
    return Response.json({ ok: true, erased: await eraseEntity(entity, id) });
  } catch (err) {
    return refuse(500, `Nothing could be erased: ${String(err).slice(0, 200)}`);
  }
}
