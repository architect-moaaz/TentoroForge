/**
 * The database is in step with the definition, or the run stops here.
 *
 * `drizzle-kit push` exits 0 when it fails: a statement Postgres refused, a
 * question it could not ask ("created or renamed?") — the build went on to
 * seed and deploy an app whose code reads columns the database does not have.
 * F&B shipped without `orders.fulfilled` that way, and the database tests of
 * 2026-10-01 found the same silence behind a refused type change and every
 * rename. Exit codes cannot be trusted, so the database itself is asked:
 * every table and column the schema declares must be there, of its type.
 */
import { is } from "drizzle-orm";
import { PgTable, getTableConfig } from "drizzle-orm/pg-core";
import postgres from "postgres";

import * as schema from "./schema";

/** information_schema's name for a type -> the family drizzle declares. */
const FAMILY: Record<string, string> = {
  "timestamp without time zone": "timestamp", "timestamp with time zone": "timestamp with time zone",
  "time without time zone": "time", "character varying": "varchar", "double precision": "double precision",
  "USER-DEFINED": "*", "ARRAY": "*",
};
const family = (t: string) => t.toLowerCase().replace(/\(.*\)$/, "").replace(/\[\]$/, "").trim();

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    console.error("[verify-schema] DATABASE_URL missing");
    process.exit(1);
  }
  const sql = postgres(url, { max: 1 });
  const wrong: string[] = [];
  let tables = 0;
  try {
    for (const value of Object.values(schema as Record<string, unknown>)) {
      if (!is(value, PgTable)) continue;
      const config = getTableConfig(value as PgTable);
      const schemaName = config.schema ?? "public";
      const rows = await sql<{ column_name: string; data_type: string }[]>`
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = ${schemaName} AND table_name = ${config.name}`;
      if (!rows.length) {
        wrong.push(`table ${config.name} is not in the database`);
        continue;
      }
      tables += 1;
      const have = new Map(rows.map((r) => [r.column_name, FAMILY[r.data_type] ?? family(r.data_type)]));
      for (const column of config.columns) {
        const type = have.get(column.name);
        if (type === undefined) {
          wrong.push(`${config.name}.${column.name} is not in the database`);
          continue;
        }
        const want = family(column.getSQLType());
        const same = type === "*" || type === want || (want === "serial" && type === "integer")
          || (want === "bigserial" && type === "bigint") || (want.startsWith("vector") && type === "*");
        if (!same) wrong.push(`${config.name}.${column.name} is ${type} in the database, ${want} in the definition`);
      }
    }
  } finally {
    await sql.end();
  }
  if (wrong.length) {
    console.error("[verify-schema] the database is NOT in step with the definition:\n"
      + wrong.map((w) => `  - ${w}`).join("\n")
      + "\nThe schema push above did not apply all of it. The app would fail on these, so this stops here.");
    process.exit(1);
  }
  console.log(`[verify-schema] the database is in step with the definition (${tables} tables)`);
}

main().catch((err) => {
  console.error("[verify-schema] failed:", err);
  process.exit(1);
});
