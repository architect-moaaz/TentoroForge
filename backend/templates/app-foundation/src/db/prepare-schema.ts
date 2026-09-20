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

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    console.error("[prepare-schema] DATABASE_URL missing");
    process.exit(1);
  }
  const sql = postgres(url, { max: 1 });
  const blocked: string[] = [];
  let added = 0;
  try {
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
  } finally {
    await sql.end();
  }
  if (blocked.length) {
    console.error(
      "[prepare-schema] the database cannot take the definition's uniqueness:\n"
      + blocked.map((b) => `  - ${b}`).join("\n")
      + "\nMerge or remove the duplicate rows, then run this again. Nothing was changed.",
    );
    process.exit(1);
  }
  console.log(added ? `[prepare-schema] ${added} constraint(s) added` : "[prepare-schema] nothing to add");
}

main().catch((err) => {
  console.error("[prepare-schema] failed:", err);
  process.exit(1);
});
