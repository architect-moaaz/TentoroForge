/**
 * GET /api/export/[entity] — streams a CSV of an entity's rows.
 * `[entity]` is the table name (e.g. "customers"). Forge runtime — do not remove.
 */
import { db } from "@/db";
import * as schema from "@/db/schema";
import { getTableName, is, Table } from "drizzle-orm";

export const runtime = "nodejs";

function resolveTable(name: string): any {
  const want = name.toLowerCase();
  for (const v of Object.values(schema as Record<string, unknown>)) {
    if (is(v as any, Table)) {
      const tn = getTableName(v as any).toLowerCase();
      if (tn === want || tn === want + "s" || tn.replace(/s$/, "") === want) return v;
    }
  }
  return undefined;
}

function cell(v: unknown): string {
  if (v == null) return "";
  const s = typeof v === "object" ? JSON.stringify(v) : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function toCsv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";
  const cols = Array.from(
    rows.reduce((set, r) => { Object.keys(r).forEach((k) => set.add(k)); return set; }, new Set<string>()),
  );
  const head = cols.join(",");
  const body = rows.map((r) => cols.map((c) => cell(r[c])).join(",")).join("\n");
  return `${head}\n${body}`;
}

export async function GET(_req: Request, { params }: { params: Promise<{ entity: string }> }): Promise<Response> {
  const { entity } = await params;
  const table = resolveTable(entity);
  if (!table) return new Response(`Unknown entity: ${entity}`, { status: 404 });
  try {
    const rows = await db.select().from(table).limit(10000);
    const csv = toCsv(rows as Record<string, unknown>[]);
    return new Response(csv, {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="${entity}.csv"`,
      },
    });
  } catch (err) {
    console.error("[api/export]", err);
    return new Response(`Export failed: ${String(err)}`, { status: 500 });
  }
}
