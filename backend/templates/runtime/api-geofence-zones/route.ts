/**
 * /api/geofence/zones — the zones, and their upkeep.
 *
 *   GET                          every zone (any signed-in person)
 *   POST   { name, shape, rules?, active?, owner?, assign? }         add one  (zone managers)
 *   PATCH  ?id=  { name?, shape?, rules?, active?, assign? }         change one
 *   DELETE ?id=                                                      remove one, with its states, crossings and rules
 *
 *   shape: { type: "circle", center: {lat,lng}, radiusM } | { type: "polygon", ring: [{lat,lng}, …] }
 *   assign: ["Order:*", "Driver:abc"] — who the zone watches; none = everyone
 *
 * Every shape is checked (radius 5 m–100 km, 3–500 corners, a real area) and every rule field is kept within sane limits.
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { sql } from "drizzle-orm";
import { invalidShape, type Shape } from "@/lib/geofence/engine";
import { cleanFenceRules } from "@/lib/geofence/rules";
import { who, refuse } from "@/lib/geofence/access";
import { zonesChanged } from "@/lib/geofence";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const rowsOf = (r: unknown): any[] => (Array.isArray(r) ? r : ((r as { rows?: any[] })?.rows ?? []));
const json = (v: unknown) => (typeof v === "string" ? JSON.parse(v) : v);

const cleanAssign = (a: unknown): string[] | null =>
  Array.isArray(a) ? a.map(String).filter((x) => /^[\w.-]+:[\w*.-]+$/.test(x)).slice(0, 200) : null;

async function readAll() {
  const zones = rowsOf(await db.execute(sql`SELECT id, name, shape, rules, active, owner, created_at FROM forge_geofences ORDER BY created_at`));
  const assigns = rowsOf(await db.execute(sql`SELECT geofence_id, subject_type, subject_id FROM forge_geofence_assignments`));
  return zones.map((z) => ({
    id: String(z.id), name: z.name, shape: json(z.shape), rules: json(z.rules) ?? {}, active: z.active !== false, owner: z.owner ? json(z.owner) : null,
    assign: assigns.filter((a) => String(a.geofence_id) === String(z.id)).map((a) => `${a.subject_type}:${a.subject_id}`),
  }));
}

async function setAssign(id: string, list: string[]) {
  await db.execute(sql`DELETE FROM forge_geofence_assignments WHERE geofence_id = ${id}::uuid`);
  for (const a of list) {
    const [t, ...rest] = a.split(":");
    await db.execute(sql`INSERT INTO forge_geofence_assignments (geofence_id, subject_type, subject_id) VALUES (${id}::uuid, ${t}, ${rest.join(":") || "*"}) ON CONFLICT DO NOTHING`);
  }
}

export async function GET(): Promise<Response> {
  const me = await who();
  if (!me.ok) return refuse(me.status, me.error);
  try {
    return Response.json({ ok: true, zones: await readAll(), canManage: me.manager });
  } catch (err) {
    return refuse(500, `The zones could not be read: ${String(err).slice(0, 200)}`);
  }
}

export async function POST(req: Request): Promise<Response> {
  const me = await who();
  if (!me.ok) return refuse(me.status, me.error);
  if (!me.manager) return refuse(403, "Only a zone manager may add a zone.");
  const b = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  const name = typeof b.name === "string" ? b.name.trim().slice(0, 120) : "";
  if (!name) return refuse(400, "A zone needs a name.");
  const bad = invalidShape(b.shape as Shape);
  if (bad) return refuse(400, bad);
  const { rules, problem } = cleanFenceRules(b.rules);
  if (problem) return refuse(400, problem);
  const assign = cleanAssign(b.assign);
  if (Array.isArray(b.assign) && assign && assign.length !== b.assign.length) return refuse(400, "Each entry of who the zone watches must look like Entity:id (letters, digits, . _ - and * for all), at most 200 of them. A zone that dropped a bad entry would watch everyone.");
  try {
    const id = String(rowsOf(await db.execute(sql`
      INSERT INTO forge_geofences (name, shape, rules, active, owner, created_by)
      VALUES (${name}, ${JSON.stringify(b.shape)}::jsonb, ${JSON.stringify(rules)}::jsonb, ${b.active !== false}, ${b.owner ? JSON.stringify(b.owner) : null}::jsonb, ${me.userId})
      RETURNING id`))[0].id);
    if (assign?.length) await setAssign(id, assign);
    zonesChanged();
    return Response.json({ ok: true, id });
  } catch (err) {
    return refuse(500, `The zone could not be saved: ${String(err).slice(0, 200)}`);
  }
}

export async function PATCH(req: Request): Promise<Response> {
  const me = await who();
  if (!me.ok) return refuse(me.status, me.error);
  if (!me.manager) return refuse(403, "Only a zone manager may change a zone.");
  const id = new URL(req.url).searchParams.get("id") ?? "";
  if (!/^[0-9a-f-]{36}$/i.test(id)) return refuse(400, "id is required.");
  const b = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  try {
    const found = rowsOf(await db.execute(sql`SELECT 1 FROM forge_geofences WHERE id = ${id}::uuid`));
    if (!found.length) return refuse(404, "No such zone.");
    if (typeof b.name === "string") {
      if (!b.name.trim()) return refuse(400, "A zone needs a name.");
      await db.execute(sql`UPDATE forge_geofences SET name = ${b.name.trim().slice(0, 120)}, updated_at = NOW() WHERE id = ${id}::uuid`);
    }
    if (b.shape !== undefined) {
      const bad = invalidShape(b.shape as Shape);
      if (bad) return refuse(400, bad);
      await db.execute(sql`UPDATE forge_geofences SET shape = ${JSON.stringify(b.shape)}::jsonb, updated_at = NOW() WHERE id = ${id}::uuid`);
    }
    if (b.rules !== undefined) {
      const { rules, problem } = cleanFenceRules(b.rules);
      if (problem) return refuse(400, problem);
      await db.execute(sql`UPDATE forge_geofences SET rules = ${JSON.stringify(rules)}::jsonb, updated_at = NOW() WHERE id = ${id}::uuid`);
    }
    if (typeof b.active === "boolean") await db.execute(sql`UPDATE forge_geofences SET active = ${b.active}, updated_at = NOW() WHERE id = ${id}::uuid`);
    const assign = cleanAssign(b.assign);
    if (Array.isArray(b.assign) && assign && assign.length !== b.assign.length) return refuse(400, "Each entry of who the zone watches must look like Entity:id (letters, digits, . _ - and * for all), at most 200 of them. A zone that dropped a bad entry would watch everyone.");
    if (assign) await setAssign(id, assign);
    zonesChanged();
    return Response.json({ ok: true });
  } catch (err) {
    return refuse(500, `The zone could not be changed: ${String(err).slice(0, 200)}`);
  }
}

export async function DELETE(req: Request): Promise<Response> {
  const me = await who();
  if (!me.ok) return refuse(me.status, me.error);
  if (!me.manager) return refuse(403, "Only a zone manager may remove a zone.");
  const id = new URL(req.url).searchParams.get("id") ?? "";
  if (!/^[0-9a-f-]{36}$/i.test(id)) return refuse(400, "id is required.");
  try {
    for (const t of ["forge_geofence_rules", "forge_geofence_state", "forge_geofence_events", "forge_geofence_assignments"]) {
      await db.execute(sql.raw(`DELETE FROM ${t} WHERE geofence_id = '${id}'::uuid`));
    }
    await db.execute(sql`DELETE FROM forge_geofences WHERE id = ${id}::uuid`);
    zonesChanged();
    return Response.json({ ok: true });
  } catch (err) {
    return refuse(500, `The zone could not be removed: ${String(err).slice(0, 200)}`);
  }
}
