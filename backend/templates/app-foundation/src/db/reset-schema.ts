/**
 * Deploy-time DB preparation — runs before `drizzle-kit push` in the build.
 *
 * WHY A RESET EXISTS AT ALL. Neon branches persist across deployments. When
 * the app's schema changes, `drizzle-kit push --force` sometimes emits DDL
 * that Postgres refuses (e.g. `DROP CONSTRAINT "<table>_id_not_null"` on a PK
 * column, since a PK implies NOT NULL and the constraint is only implicit).
 * The push bails partway, `seed.ts` skips affected tables, and the app 500s at
 * runtime on a query for a column that never landed. Dropping and recreating
 * `public` made that go away.
 *
 * WHY IT NO LONGER DROPS BY DEFAULT. It was justified by "the generated app
 * has no user data worth preserving across deploys". That is true of an app
 * nobody has used, and false the moment somebody enters something — and the
 * end user's path is to click publish, which runs this. Destroying data should
 * take intent, not the absence of an environment variable.
 *
 * So the rule is: if any domain table holds a row, the database is migrated in
 * place and nothing is dropped. If every domain table is empty, the database
 * holds nothing to lose and the reset does its original job.
 *
 * Scaffold tables are not domain data. `seed.ts` writes an admin user on every
 * deploy, and the `_forge_*` tables are runtime bookkeeping; counting those
 * would mean the reset never ran after the first deploy, including on the
 * broken-DDL case it exists for.
 *
 * `FORGE_KEEP_DB_STATE=1` still forces preservation, for a caller that knows
 * the tables are empty and wants them kept anyway.
 *
 * WHAT HAPPENS WHEN PUSH THEN FAILS on a schema it cannot migrate in place:
 * the build fails, with the push's own error. That is the right outcome. A
 * failed deployment is recoverable; an emptied database is not.
 */
import postgres from "postgres";

/** Tables the scaffold owns. Rows here are not the user's work. */
const SCAFFOLD_TABLES = new Set([
  "users", "user", "accounts", "sessions", "verification_tokens",
  "__drizzle_migrations",
]);

const isScaffold = (name: string) =>
  SCAFFOLD_TABLES.has(name) || name.startsWith("_forge_") ||
  name.startsWith("drizzle");

// Wrapped in an async IIFE — tsx transforms to CJS in Vercel builds,
// which rejects top-level await.
async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    console.error("[reset-schema] DATABASE_URL missing");
    process.exit(1);
  }
  const sql = postgres(url, { max: 1 });
  try {
    if (process.env.FORGE_KEEP_DB_STATE === "1") {
      console.log("[reset-schema] FORGE_KEEP_DB_STATE=1 — migrating in place");
      return;
    }

    const tables = await sql<{ table_name: string }[]>`
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    `;
    const domain = tables
      .map((t) => t.table_name)
      .filter((name) => !isScaffold(name));

    // ONE ROW IS ENOUGH TO STOP THIS. Counting every row would read whole
    // tables for an answer that needs one; `LIMIT 1` asks only whether
    // anything is there.
    const holding: string[] = [];
    for (const table of domain) {
      const rows = await sql.unsafe(
        `SELECT 1 FROM "${table.replace(/"/g, '""')}" LIMIT 1`,
      );
      if (rows.length) holding.push(table);
    }

    if (holding.length) {
      console.log(
        `[reset-schema] ${holding.join(", ")} hold data — migrating in place, `
        + "nothing dropped",
      );
      return;
    }

    console.log(
      domain.length
        ? `[reset-schema] ${domain.length} domain table(s), all empty — resetting`
        : "[reset-schema] no domain tables — resetting",
    );
    await sql.unsafe("DROP SCHEMA public CASCADE");
    await sql.unsafe("CREATE SCHEMA public");
    console.log("[reset-schema] done");
  } finally {
    await sql.end();
  }
}

main().catch((err) => {
  console.error("[reset-schema] failed:", err);
  process.exit(1);
});
