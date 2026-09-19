/**
 * Postgres extensions the generated schema may use — runs before
 * `drizzle-kit push`, from reset-schema.ts on deploy and on its own for a
 * local preview (`npx tsx src/db/extensions.ts`).
 *
 * `vector` (pgvector) backs embedding fields: a Blueprint field declared
 * `{type: "vector", embedding: {of: ...}}` is a `vector(512)` column with an
 * HNSW index, and push cannot create either without the extension.
 *
 * It is created for every app rather than only the ones that declare an
 * embedding, because this file is refreshed into apps that predate the
 * manifest and cannot read it. A database without pgvector available (a
 * plain `postgres` image) is fine for an app that declares none: the failure
 * is logged and push goes on. For an app that does, push then fails on the
 * `vector` type with its own error, which is the right place to learn it.
 */
import postgres from "postgres";

const EXTENSIONS = ["vector"];

export async function ensureExtensions(sql: postgres.Sql): Promise<void> {
  for (const name of EXTENSIONS) {
    try {
      await sql.unsafe(`CREATE EXTENSION IF NOT EXISTS "${name}"`);
    } catch (err) {
      console.warn(
        `[extensions] ${name} unavailable on this database — `
        + `an embedding field needs a Postgres with pgvector: ${(err as Error).message}`,
      );
    }
  }
}

// Run directly: `npx tsx src/db/extensions.ts`. Wrapped rather than top-level
// await for the same reason as reset-schema.ts (tsx → CJS on Vercel).
if (process.argv[1] && /extensions\.[cm]?[tj]s$/.test(process.argv[1])) {
  (async () => {
    const url = process.env.DATABASE_URL;
    if (!url) {
      console.error("[extensions] DATABASE_URL missing");
      process.exit(1);
    }
    const sql = postgres(url, { max: 1 });
    try {
      await ensureExtensions(sql);
    } finally {
      await sql.end();
    }
  })().catch((err) => {
    console.error("[extensions] failed:", err);
    process.exit(1);
  });
}
