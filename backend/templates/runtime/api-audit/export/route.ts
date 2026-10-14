/** GET /api/audit/export — the trail as CSV, for its reviewers; the export is itself on the record. */
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { actorOf, recordAudit, regulated } from "@/lib/audit";
import { reviewer } from "../route";

export const runtime = "nodejs";

const COLS = ["seq", "at", "actor_id", "actor_role", "actor_kind", "via", "run_id", "action", "entity", "entity_id",
              "before", "after", "changed", "reason", "prev_hash", "hash"];

function cell(v: unknown): string {
  const s = v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, "\"\"")}"` : s;
}

export async function GET(): Promise<Response> {
  const who = await reviewer();
  if (!who.ok) return new Response(who.error, { status: who.status });
  const res: any = await db.execute(sql`SELECT ${sql.raw(COLS.join(", "))} FROM forge_audit ORDER BY seq ASC LIMIT 100000`);
  const rows: any[] = Array.isArray(res) ? res : (res?.rows ?? []);
  const csv = [COLS.join(","), ...rows.map((r) => COLS.map((c) => cell(r[c])).join(","))].join("\n") + "\n";
  if (regulated()) {
    await recordAudit(db, { action: "export", entity: "forge_audit", after: { rows: rows.length }, actor: actorOf(who.user), via: "export" })
      .catch((e: unknown) => console.warn("[audit] the export could not be recorded:", e));
  }
  return new Response(csv, { headers: { "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": `attachment; filename="audit-${new Date().toISOString().slice(0, 10)}.csv"` } });
}
