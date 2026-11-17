/**
 * /api/geofence/rules — "when this happens at this zone, do this".
 *
 *   GET     ?zone=<id>                      the rules (zone managers)
 *   POST    { geofenceId?, onEvent, condition?, action, confirm?, sensitive? }
 *   DELETE  ?id=
 *
 * A rule is checked when it is saved (the event, the action, the condition) and saved as it will run: a rule that moves
 * money, finishes a job or marks someone present is stored as SENSITIVE and runs only after the confirmation it names.
 * The answer to a POST says whether the rule is sensitive and what it will wait for, so the screen can show it.
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { sql } from "drizzle-orm";
import { invalidRule, isSensitive, type Rule } from "@/lib/geofence/rules";
import { who, refuse } from "@/lib/geofence/access";
import { rulesChanged } from "@/lib/geofence";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const rowsOf = (r: unknown): any[] => (Array.isArray(r) ? r : ((r as { rows?: any[] })?.rows ?? []));
const json = (v: unknown) => (typeof v === "string" ? JSON.parse(v) : v);
const UUID = /^[0-9a-f-]{36}$/i;

async function manager() {
  const me = await who();
  if (!me.ok) return { err: refuse(me.status, me.error) };
  if (!me.manager) return { err: refuse(403, "Only a zone manager may work with rules.") };
  return { me };
}

export async function GET(req: Request): Promise<Response> {
  const m = await manager();
  if (m.err) return m.err;
  const zone = new URL(req.url).searchParams.get("zone");
  try {
    const rows = rowsOf(await db.execute(zone && UUID.test(zone)
      ? sql`SELECT id, geofence_id, on_event, condition, action, sensitive, confirm, active FROM forge_geofence_rules WHERE geofence_id = ${zone}::uuid OR geofence_id IS NULL ORDER BY created_at`
      : sql`SELECT id, geofence_id, on_event, condition, action, sensitive, confirm, active FROM forge_geofence_rules ORDER BY created_at`));
    const rules = rows.map((r) => {
      const rule: Rule = { id: String(r.id), geofenceId: r.geofence_id ? String(r.geofence_id) : null, onEvent: r.on_event, condition: r.condition, action: json(r.action), sensitive: !!r.sensitive, confirm: r.confirm ? json(r.confirm) : null, active: r.active !== false };
      return { ...rule, willWaitFor: isSensitive(rule) ? (rule.confirm?.event ?? "(nothing named: it will never run)") : null };
    });
    return Response.json({ ok: true, rules });
  } catch (err) {
    return refuse(500, `The rules could not be read: ${String(err).slice(0, 200)}`);
  }
}

export async function POST(req: Request): Promise<Response> {
  const m = await manager();
  if (m.err) return m.err;
  const b = (await req.json().catch(() => ({}))) as Partial<Rule> & { geofenceId?: string | null };
  const bad = invalidRule(b);
  if (bad) return refuse(400, bad);
  if (b.geofenceId && !UUID.test(b.geofenceId)) return refuse(400, "geofenceId is not a zone id.");
  const confirm = b.confirm && typeof b.confirm.event === "string" && b.confirm.event.trim()
    ? { event: b.confirm.event.trim(), ...(b.confirm.withinSec ? { withinSec: Math.max(1, Math.min(Number(b.confirm.withinSec) || 0, 86_400)) } : {}) }
    : null;
  const rule = { ...b, confirm } as Rule;
  const sensitive = isSensitive(rule);
  try {
    const id = String(rowsOf(await db.execute(sql`
      INSERT INTO forge_geofence_rules (geofence_id, on_event, condition, action, sensitive, confirm)
      VALUES (${b.geofenceId ?? null}::uuid, ${b.onEvent}, ${b.condition ?? null}, ${JSON.stringify(b.action)}::jsonb, ${sensitive}, ${confirm ? JSON.stringify(confirm) : null}::jsonb)
      RETURNING id`))[0].id);
    rulesChanged();
    return Response.json({ ok: true, id, sensitive, willWaitFor: sensitive ? (confirm?.event ?? null) : null,
      warning: sensitive && !confirm ? "This rule moves money, finishes a job or marks someone present. It is saved, but it will never run until you name the confirmation it waits for." : undefined });
  } catch (err) {
    return refuse(500, `The rule could not be saved: ${String(err).slice(0, 200)}`);
  }
}

export async function DELETE(req: Request): Promise<Response> {
  const m = await manager();
  if (m.err) return m.err;
  const id = new URL(req.url).searchParams.get("id") ?? "";
  if (!UUID.test(id)) return refuse(400, "id is required.");
  try {
    await db.execute(sql`DELETE FROM forge_geofence_rules WHERE id = ${id}::uuid`);
    rulesChanged();
    return Response.json({ ok: true });
  } catch (err) {
    return refuse(500, `The rule could not be removed: ${String(err).slice(0, 200)}`);
  }
}
