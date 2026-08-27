/**
 * GET /api/_debug/seed-status
 *
 * Diagnostic endpoint: compares the seed-plan's expected rows-per-entity
 * against the actual `SELECT count(*)` from Postgres, per table. Read-only
 * — safe to leave enabled in every environment. The response makes silent
 * seed failures (rows planned but never inserted) trivially observable
 * without direct DB access.
 *
 * Response shape:
 *   {
 *     ok: boolean,          // true iff every table has >= expected rows
 *     tables: [{
 *       name:     string,   // registry entity name (e.g. "PaymentMethod")
 *       table:    string,   // actual DB table (e.g. "payment_methods")
 *       expected: number,   // from seed-plan.json row_count
 *       actual:   number,   // live SELECT count(*)
 *       delta:    number,   // actual - expected
 *       status:   "match" | "under" | "over" | "missing" | "error",
 *       error?:   string,
 *     }],
 *     summary: {tables: number, under: number, error: number, missing: number}
 *   }
 *
 * Emitted by runtime_injector; imports are patched at generation time to
 * point at every discovered `src/db/schema/*.ts` file (mirrors the data
 * API route's discovery pattern).
 */
import { NextResponse } from "next/server";
import { sql } from "drizzle-orm";
import { promises as fs } from "node:fs";
import path from "node:path";
import { getTableName } from "drizzle-orm";
import { db } from "@/db";

type PlanTable = { name?: string; row_count?: number };
type PlanFile = { tables?: PlanTable[] };

// GENERATED IMPORTS PLACEHOLDER — runtime_injector replaces this with one
// `import * as schema_<n> from "@/db/schema/<file>";` per discovered schema.
import * as _seedschema_0 from "@/db/schema/documents";
import * as _seedschema_1 from "@/db/schema/user";

// GENERATED SCHEMA MODULES PLACEHOLDER — runtime_injector replaces this
// with an array of the imported modules for iteration below.
const SCHEMA_MODULES: Array<Record<string, unknown>> = [_seedschema_0, _seedschema_1];


const AUX_TABLE_PREFIX = "forge_"; // skip internal bookkeeping tables

function collectTables(): Map<string, unknown> {
  const out = new Map<string, unknown>();
  for (const mod of SCHEMA_MODULES) {
    if (!mod || typeof mod !== "object") continue;
    for (const [key, val] of Object.entries(mod)) {
      // Drizzle pgTable objects expose `getTableName(t) === "<name>"`.
      // Anything without that shape is a relations helper — skip.
      try {
        const name = getTableName(val as any);
        if (typeof name === "string" && !name.startsWith(AUX_TABLE_PREFIX)
            && !name.startsWith("_forge_")) {
          out.set(name, val);
        }
      } catch {
        // not a table export
      }
      void key;
    }
  }
  return out;
}

async function readSeedPlan(): Promise<PlanFile> {
  const candidates = [
    path.join(process.cwd(), "contracts", "seed-plan.json"),
    path.join(process.cwd(), "src", "contracts", "seed-plan.json"),
  ];
  for (const p of candidates) {
    try {
      const text = await fs.readFile(p, "utf8");
      return JSON.parse(text) as PlanFile;
    } catch {
      /* try next */
    }
  }
  return {};
}

function expectedByTable(plan: PlanFile): Map<string, number> {
  const out = new Map<string, number>();
  for (const t of plan.tables ?? []) {
    if (!t?.name || typeof t.row_count !== "number") continue;
    // Match by entity name → snake_case table name so `PaymentMethod` maps
    // to `payment_methods`. `getTableName` gives the canonical table name.
    const snake = t.name
      .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
      .toLowerCase();
    out.set(snake + "s", t.row_count);       // plural table convention
    out.set(snake, t.row_count);              // singular fallback
  }
  return out;
}

export async function GET() {
  const tables = collectTables();
  const plan = await readSeedPlan();
  const expected = expectedByTable(plan);
  const results: Array<Record<string, unknown>> = [];

  for (const [name, tbl] of tables) {
    const exp = expected.get(name) ?? 0;
    try {
      const rows = await db.execute(sql.raw(`SELECT count(*)::int AS c FROM "${name}"`));
      const actual = Number((rows as any).rows?.[0]?.c ?? (rows as any)[0]?.c ?? 0);
      let status: string;
      if (actual === 0 && exp > 0) status = "missing";
      else if (actual < exp) status = "under";
      else if (actual > exp) status = "over";
      else status = "match";
      results.push({
        name,
        table: name,
        expected: exp,
        actual,
        delta: actual - exp,
        status,
      });
    } catch (e: any) {
      results.push({
        name,
        table: name,
        expected: exp,
        actual: 0,
        delta: -exp,
        status: "error",
        error: String(e?.message ?? e),
      });
    }
    void tbl;
  }

  const summary = {
    tables: results.length,
    under: results.filter((r) => r.status === "under").length,
    missing: results.filter((r) => r.status === "missing").length,
    error: results.filter((r) => r.status === "error").length,
  };
  const ok =
    summary.under === 0 && summary.missing === 0 && summary.error === 0;
  return NextResponse.json({ ok, summary, tables: results });
}
