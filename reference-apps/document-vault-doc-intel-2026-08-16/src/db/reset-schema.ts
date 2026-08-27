/**
 * Deploy-time DB reset — runs before `drizzle-kit push` in the build.
 *
 * Neon branches persist across deployments. When the app's schema.ts
 * changes (new columns, dropped tables, altered PKs), `drizzle-kit
 * push --force` sometimes emits DDL that Postgres refuses (e.g.
 * `DROP CONSTRAINT "<table>_id_not_null"` on a PK column, since a PK
 * implies NOT NULL and the constraint is only implicit).  The push
 * bails partway, subsequent `seed.ts` skips affected tables, and the
 * app 500s at runtime on any query for a missing column.
 *
 * Cheapest fix: drop and recreate the `public` schema before push.
 * The generated app has no user data worth preserving across deploys
 * (every deploy re-runs seed.ts to repopulate), so the reset is safe.
 *
 * If a future generated app needs cross-deploy data survival, gate this
 * behind an env flag (e.g. `FORGE_KEEP_DB_STATE=1`) — for now, plain
 * reset is the right default.
 */
import postgres from "postgres";

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
    console.log("[reset-schema] dropping public schema + contents");
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
