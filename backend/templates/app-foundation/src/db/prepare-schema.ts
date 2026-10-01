/**
 * Makes `drizzle-kit push` unable to ask a question. Runs before it, in the
 * build and at every start.
 *
 * WHAT ASKED ONE. A definition that says a rental has at most one dispute
 * projects `rentalId: uuid("rental_id").notNull().unique()`. On a database
 * whose `disputes` table already holds rows, push does not add that
 * constraint by itself — it asks:
 *
 *     You're about to add disputes_rental_id_unique unique constraint to the
 *     table, which contains 3 items. Do you want to truncate disputes table?
 *
 * and waits at that question. `--force` does not cover it and neither does
 * reading EOF: it waited on a terminal that had /dev/null on its stdin. In a
 * Vercel build there is nobody to answer at all, so the deployment sits there
 * until the clock runs out — on a question about destroying the user's data.
 *
 * SO THE CONSTRAINT IS ADDED HERE, FIRST. Every unique the schema declares
 * that the database does not have yet is added with plain DDL, after reading
 * whether the rows can take it. Push then finds nothing to ask about.
 *
 * Rows that already break the uniqueness are the one case where nothing can
 * be added, and that is said in full — which table, which column, which value
 * appears twice — and the run fails. A failed deploy that names the two rows
 * to merge is worth more than a build that hangs for twenty minutes, and much
 * more than a truncated table.
 */
import fs from "node:fs";
import { is } from "drizzle-orm";
import { PgTable, getTableConfig } from "drizzle-orm/pg-core";
import postgres from "postgres";

import * as schema from "./schema";

type Unique = { name: string; columns: string[] };

/** Every unique the schema declares, per table, however it was written. */
export function declaredUniques(): Map<string, Unique[]> {
  const out = new Map<string, Unique[]>();
  for (const value of Object.values(schema as Record<string, unknown>)) {
    if (!is(value, PgTable)) continue;
    const config = getTableConfig(value as PgTable);
    const uniques: Unique[] = [];
    for (const column of config.columns) {
      // A primary key is unique already and carries no separate constraint.
      if (!column.isUnique || column.primary) continue;
      uniques.push({
        name: column.uniqueName ?? `${config.name}_${column.name}_unique`,
        columns: [column.name],
      });
    }
    for (const constraint of config.uniqueConstraints ?? []) {
      uniques.push({
        name: constraint.name ?? `${config.name}_${constraint.columns.map((c) => c.name).join("_")}_unique`,
        columns: constraint.columns.map((c) => c.name),
      });
    }
    if (uniques.length) out.set(config.name, uniques);
  }
  return out;
}

const quote = (name: string) => `"${name.replace(/"/g, '""')}"`;

/** Postgres' name for a type (information_schema.data_type) -> drizzle's. */
const PG_NAME: Record<string, string> = {
  "timestamp without time zone": "timestamp", "time without time zone": "time",
  "date": "date", "integer": "integer", "numeric": "numeric", "text": "text",
  "boolean": "boolean", "bigint": "bigint", "real": "real", "double precision": "double precision",
  "character varying": "varchar", "uuid": "uuid", "jsonb": "jsonb",
  "timestamp with time zone": "timestamp with time zone",
};

/** Types a value can be cast between with `::`, when every value fits. */
const CASTABLE = new Set(["text", "varchar", "integer", "bigint", "numeric", "real", "double precision",
  "boolean", "date", "timestamp", "time", "uuid"]);

/** The type family of a declared SQL type: `varchar(255)` is `varchar`. */
const family = (t: string) => t.toLowerCase().replace(/\(.*\)$/, "").trim();

/**
 * A COLUMN WHOSE TYPE THE DEFINITION CHANGED IS CONVERTED HERE, FIRST — when
 * the old value means the same thing in the new type. Push reads any type
 * change as data loss and offers to empty the table; with `--force` it says
 * yes. Med Tracker's `preferred_time` was projected a timestamp for a time of
 * day; correcting it to `time` would have emptied every medicine (2026-09-29).
 * Only these conversions are made; any other change is left to push, as before.
 */
const KEEPS_ITS_MEANING: Record<string, string[]> = {
  timestamp: ["time", "date"],
  date: ["timestamp"],
  integer: ["numeric"],
};

/** Every column's declared SQL type, per table. */
export function declaredTypes(): Map<string, Map<string, string>> {
  const out = new Map<string, Map<string, string>>();
  for (const value of Object.values(schema as Record<string, unknown>)) {
    if (!is(value, PgTable)) continue;
    const config = getTableConfig(value as PgTable);
    const cols = new Map<string, string>();
    for (const column of config.columns) cols.set(column.name, column.getSQLType().toLowerCase());
    out.set(config.name, cols);
  }
  return out;
}

const blockedTypes: string[] = [];

type Sql = ReturnType<typeof postgres>;

async function tableExists(sql: Sql, table: string): Promise<boolean> {
  const r = await sql`SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ${table}`;
  return r.length > 0;
}

async function columnsOf(sql: Sql, table: string): Promise<Map<string, { type: string; nullable: boolean }>> {
  const rows = await sql<{ column_name: string; data_type: string; is_nullable: string }[]>`
    SELECT column_name, data_type, is_nullable FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = ${table}`;
  return new Map(rows.map((r) => [r.column_name, { type: r.data_type, nullable: r.is_nullable === "YES" }]));
}

/**
 * A RENAME IS A RENAME. Push cannot tell a renamed column from a dropped one
 * and a new one; it asks, and in a build nobody can answer — it crashed,
 * exited 0, and left the old name in place under code reading the new one
 * (database tests, 2026-10-01). Smith's rename tools write each rename to
 * `src/db/migrations.json`; it is applied here, in order, where the old name
 * is still there and the new one is not — so it runs once on every database,
 * however far behind.
 */
async function applyRenames(sql: Sql): Promise<string[]> {
  const done: string[] = [];
  let ledger: { tables?: { from: string; to: string }[]; columns?: { table: string; from: string; to: string }[] } = {};
  try {
    ledger = JSON.parse(fs.readFileSync("src/db/migrations.json", "utf8"));
  } catch {
    return done;
  }
  for (const t of ledger.tables ?? []) {
    if (await tableExists(sql, t.from) && !(await tableExists(sql, t.to))) {
      await sql.unsafe(`ALTER TABLE ${quote(t.from)} RENAME TO ${quote(t.to)}`);
      done.push(`table ${t.from} -> ${t.to}`);
    }
  }
  for (const c of ledger.columns ?? []) {
    if (!(await tableExists(sql, c.table))) continue;
    const cols = await columnsOf(sql, c.table);
    if (cols.has(c.from) && !cols.has(c.to)) {
      await sql.unsafe(`ALTER TABLE ${quote(c.table)} RENAME COLUMN ${quote(c.from)} TO ${quote(c.to)}`);
      done.push(`${c.table}.${c.from} -> ${c.to}`);
    }
  }
  return done;
}

/** What existing rows are given for a required column they never had. */
const FILL: Record<string, string> = {
  text: "''", varchar: "''", integer: "0", bigint: "0", numeric: "0", real: "0",
  "double precision": "0", boolean: "false", date: "CURRENT_DATE", timestamp: "now()",
  "timestamp with time zone": "now()", time: "'00:00'", jsonb: "'{}'::jsonb",
};

/**
 * A REQUIRED COLUMN ON A TABLE THAT HOLDS ROWS IS ADDED HERE, AND THE ROWS
 * KEPT. Push cannot add a NOT NULL column to rows that have no value; with
 * `--force` it EMPTIED THE TABLE to do it — five orders gone for a table-number
 * field (database tests, 2026-10-01). Here the column is added, the rows
 * given a blank of its type, and only then made required; a type with no
 * blank (a reference to another record) is refused in words instead.
 */
async function addRequired(sql: Sql, blocked: string[]): Promise<string[]> {
  const done: string[] = [];
  for (const value of Object.values(schema as Record<string, unknown>)) {
    if (!is(value, PgTable)) continue;
    const config = getTableConfig(value as PgTable);
    if (!(await tableExists(sql, config.name))) continue;
    const present = await columnsOf(sql, config.name);
    const [{ n }] = await sql.unsafe(`SELECT count(*)::int AS n FROM ${quote(config.name)}`);
    if (!n) continue;
    for (const column of config.columns) {
      if (!column.notNull || column.primary || column.hasDefault) continue;
      const type = column.getSQLType();
      const have = present.get(column.name);
      const missing = await (have
        ? sql.unsafe(`SELECT count(*)::int AS n FROM ${quote(config.name)} WHERE ${quote(column.name)} IS NULL`)
        : Promise.resolve([{ n }]));
      if (have && (!have.nullable || !missing[0].n)) continue;
      const fill = FILL[family(type)];
      if (!fill) {
        blocked.push(`${config.name}.${column.name} is required, and ${missing[0].n} record(s) already there have `
          + "no value for it; give them one, or make it optional");
        continue;
      }
      await sql.begin(async (tx) => {
        if (!have) await tx.unsafe(`ALTER TABLE ${quote(config.name)} ADD COLUMN ${quote(column.name)} ${type}`);
        await tx.unsafe(`UPDATE ${quote(config.name)} SET ${quote(column.name)} = ${fill} WHERE ${quote(column.name)} IS NULL`);
        await tx.unsafe(`ALTER TABLE ${quote(config.name)} ALTER COLUMN ${quote(column.name)} SET NOT NULL`);
      });
      done.push(`${config.name}.${column.name}: ${missing[0].n} existing record(s) given ${fill}`);
    }
  }
  return done;
}

/**
 * WHAT IS TAKEN OUT OF THE DEFINITION IS KEPT. Push drops a removed column or
 * table and its data with it. Before it does, every value is copied to
 * `forge_retired.rows` — a schema push never touches — so a removal can be
 * undone with its data (database tests, 2026-10-01).
 */
async function keepRetired(sql: Sql, renamed: Set<string>): Promise<string[]> {
  const declared = new Map<string, Set<string>>();
  for (const value of Object.values(schema as Record<string, unknown>)) {
    if (!is(value, PgTable)) continue;
    const config = getTableConfig(value as PgTable);
    declared.set(config.name, new Set(config.columns.map((c) => c.name)));
  }
  const tables = await sql<{ table_name: string }[]>`
    SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'`;
  const kept: string[] = [];
  let ready = false;
  const store = async () => {
    if (ready) return;
    await sql.unsafe("CREATE SCHEMA IF NOT EXISTS forge_retired");
    await sql.unsafe(`CREATE TABLE IF NOT EXISTS forge_retired.rows (
      table_name text NOT NULL, column_name text, row jsonb NOT NULL, retired_at timestamptz NOT NULL DEFAULT now())`);
    ready = true;
  };
  for (const { table_name: t } of tables) {
    if (t.startsWith("_forge") || t.startsWith("drizzle") || renamed.has(t)) continue;
    const cols = declared.get(t);
    if (!cols) {
      const [{ n }] = await sql.unsafe(`SELECT count(*)::int AS n FROM ${quote(t)}`);
      if (!n) continue;
      await store();
      await sql.unsafe(`INSERT INTO forge_retired.rows (table_name, row) SELECT $1, to_jsonb(x) FROM ${quote(t)} x`, [t]);
      kept.push(`${t}: ${n} record(s)`);
      continue;
    }
    for (const [c] of await columnsOf(sql, t)) {
      if (cols.has(c)) continue;
      const key = (await columnsOf(sql, t)).has("id") ? "id" : null;
      const [{ n }] = await sql.unsafe(`SELECT count(*)::int AS n FROM ${quote(t)} WHERE ${quote(c)} IS NOT NULL`);
      if (!n) continue;
      await store();
      await sql.unsafe(
        `INSERT INTO forge_retired.rows (table_name, column_name, row) SELECT $1, $2, jsonb_build_object(`
        + (key ? `'id', ${quote(key)}::text, ` : "") + `'value', to_jsonb(${quote(c)})) FROM ${quote(t)} `
        + `WHERE ${quote(c)} IS NOT NULL`, [t, c]);
      kept.push(`${t}.${c}: ${n} value(s)`);
    }
  }
  return kept;
}

async function convertTypes(sql: ReturnType<typeof postgres>): Promise<number> {
  let converted = 0;
  for (const [table, cols] of declaredTypes()) {
    const present = await sql<{ column_name: string; data_type: string }[]>`
      SELECT column_name, data_type FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = ${table}
    `;
    for (const { column_name, data_type } of present) {
      const want = cols.get(column_name);
      const have = PG_NAME[data_type];
      if (!want || !have || family(want) === have) continue;
      const alter = `ALTER TABLE ${quote(table)} ALTER COLUMN ${quote(column_name)} TYPE ${want} USING ${quote(column_name)}::${want}`;
      if ((KEEPS_ITS_MEANING[have] ?? []).includes(family(want))) {
        await sql.unsafe(alter);
      } else if (CASTABLE.has(have) && CASTABLE.has(family(want))) {
        // ANY OTHER CHANGE OF TYPE IS MADE WHEN EVERY VALUE FITS, and refused
        // in words when one does not. Left to push, "status" from text to a
        // number failed in Postgres, push exited 0, the build went on, and
        // the app read a number from a column that still held "paid"
        // (database tests, 2026-10-01).
        try {
          await sql.begin(async (tx) => { await tx.unsafe(alter); });
        } catch (err) {
          const bad = await sql.unsafe(
            `SELECT ${quote(column_name)}::text AS v FROM ${quote(table)} WHERE ${quote(column_name)} IS NOT NULL LIMIT 3`);
          blockedTypes.push(`${table}.${column_name} cannot become ${want}: values such as `
            + bad.map((r: Record<string, unknown>) => JSON.stringify(r.v)).join(", ")
            + ` do not convert (${String((err as Error).message).split("\n")[0]})`);
          continue;
        }
      } else {
        continue;
      }
      converted += 1;
      console.log(`[prepare-schema] ${table}.${column_name}: ${have} -> ${want}, rows kept`);
    }
  }
  return converted;
}

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    console.error("[prepare-schema] DATABASE_URL missing");
    process.exit(1);
  }
  const sql = postgres(url, { max: 1 });
  const blocked: string[] = [];
  let added = 0;
  let converted = 0;
  let renamed: string[] = [];
  let required: string[] = [];
  let retired: string[] = [];
  try {
    renamed = await applyRenames(sql);
    converted = await convertTypes(sql);
    blocked.push(...blockedTypes);
    required = await addRequired(sql, blocked);
    for (const [table, uniques] of declaredUniques()) {
      const exists = await sql<{ table_name: string }[]>`
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = ${table}
      `;
      // A table push is about to CREATE carries its constraints with it.
      if (!exists.length) continue;
      const present = await sql<{ conname: string }[]>`
        SELECT conname FROM pg_constraint
        WHERE conrelid = ${`public.${quote(table)}`}::regclass AND contype IN ('u', 'p')
      `;
      const have = new Set(present.map((row) => row.conname));
      for (const unique of uniques) {
        if (have.has(unique.name)) continue;
        const columns = unique.columns.map(quote).join(", ");
        const duplicates = await sql.unsafe(
          `SELECT ${columns}, count(*)::int AS n FROM ${quote(table)} `
          + `GROUP BY ${columns} HAVING count(*) > 1 LIMIT 3`,
        );
        if (duplicates.length) {
          const values = duplicates
            .map((row: Record<string, unknown>) =>
              `${unique.columns.map((c) => `${c}=${JSON.stringify(row[c])}`).join(", ")} (${row.n} rows)`)
            .join("; ");
          blocked.push(
            `${table}.${unique.columns.join(", ")} must be unique, and the rows already there are not: ${values}`,
          );
          continue;
        }
        await sql.unsafe(
          `ALTER TABLE ${quote(table)} ADD CONSTRAINT ${quote(unique.name)} UNIQUE (${columns})`,
        );
        added += 1;
        console.log(`[prepare-schema] ${table}: added ${unique.name}`);
      }
    }
    if (!blocked.length) {
      const renamedTables = new Set<string>();
      retired = await keepRetired(sql, renamedTables);
    }
  } finally {
    await sql.end();
  }
  for (const r of renamed) console.log(`[prepare-schema] renamed ${r}, data kept`);
  for (const r of required) console.log(`[prepare-schema] required ${r}`);
  for (const r of retired) console.log(`[prepare-schema] kept before removal: ${r} (forge_retired.rows)`);
  if (blocked.length) {
    console.error(
      "[prepare-schema] the database cannot take the definition as it is:\n"
      + blocked.map((b) => `  - ${b}`).join("\n")
      + "\nThese were not changed, and the schema push must not run over them. Fix the records named above (or the definition), then run this again.",
    );
    process.exit(1);
  }
  console.log(added || converted || renamed.length || required.length || retired.length
    ? `[prepare-schema] ${added} constraint(s) added, ${converted} column(s) converted, `
      + `${renamed.length} renamed, ${required.length} required column(s) filled, ${retired.length} removal(s) kept`
    : "[prepare-schema] nothing to add");
}

main().catch((err) => {
  console.error("[prepare-schema] failed:", err);
  process.exit(1);
});
