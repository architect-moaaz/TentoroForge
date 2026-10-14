/**
 * GET /api/audit — the trail, for its reviewers.
 *
 * `?entity=&entityId=&actor=&action=&from=&to=&page=&limit=` — newest first.
 * Only a role the audit policy names as a reviewer may read it; everyone
 * else is answered 403. Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { auth } from "@/auth";
import { auditOn, reviewers } from "@/lib/audit";

export const runtime = "nodejs";

export async function reviewer(): Promise<{ ok: true; user: any } | { ok: false; status: number; error: string }> {
  const user = (await auth())?.user as { id?: unknown; role?: unknown } | undefined;
  if (!user?.id) return { ok: false, status: 401, error: "Sign in to read the audit trail." };
  if (!auditOn()) return { ok: false, status: 404, error: "This application keeps no audit trail." };
  if (!reviewers().includes(String(user.role ?? ""))) {
    return { ok: false, status: 403, error: "The audit trail is read by its reviewers." };
  }
  return { ok: true, user };
}

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

export async function GET(req: Request): Promise<Response> {
  const who = await reviewer();
  if (!who.ok) return NextResponse.json({ error: who.error }, { status: who.status });
  const q = new URL(req.url).searchParams;
  const limit = Math.min(Math.max(Number(q.get("limit") ?? 50) || 50, 1), 500);
  const page = Math.max(Number(q.get("page") ?? 1) || 1, 1);
  const where = [sql`TRUE`];
  if (q.get("entity")) where.push(sql`entity = ${q.get("entity")}`);
  if (q.get("entityId")) where.push(sql`entity_id = ${q.get("entityId")}`);
  if (q.get("actor")) where.push(sql`actor_id = ${q.get("actor")}`);
  if (q.get("action")) where.push(sql`action = ${q.get("action")}`);
  if (q.get("from")) where.push(sql`at >= ${q.get("from")}::timestamptz`);
  if (q.get("to")) where.push(sql`at <= ${q.get("to")}::timestamptz`);
  const cond = sql.join(where, sql` AND `);
  try {
    const rows = _rows(await db.execute(sql`
      SELECT seq, at, actor_id, actor_role, actor_kind, via, run_id, action, entity, entity_id, before, after, changed, reason
      FROM forge_audit WHERE ${cond} ORDER BY seq DESC LIMIT ${limit} OFFSET ${(page - 1) * limit}
    `));
    const total = Number(_rows(await db.execute(sql`SELECT count(*)::int AS n FROM forge_audit WHERE ${cond}`))[0]?.n ?? 0);
    return NextResponse.json({ rows, total, page, limit });
  } catch (err) {
    return NextResponse.json({ error: `the trail could not be read: ${String(err)}` }, { status: 500 });
  }
}
