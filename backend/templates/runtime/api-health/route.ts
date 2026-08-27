/**
 * GET /api/health/db — deploy-time smoke endpoint.
 *
 * Returns 200 with `{ok: true}` iff the Postgres connection is live AND at
 * least one application table exists in the public schema. Returns 503 with
 * an explanatory error otherwise.
 *
 * Used by the platform's deploy provider immediately after Vercel reports
 * READY — a green Vercel build with a broken DB (empty schema, wrong
 * DATABASE_URL, unreachable Neon) is the exact class of silent failure this
 * catches. Safe to hit repeatedly; no side effects. Forge runtime — do not remove.
 */
import { db } from "@/db";
import { sql } from "drizzle-orm";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try {
    // 1. Can we talk to Postgres at all?
    const [ping] = (await db.execute(sql`select 1 as ok`)) as unknown as [
      { ok: number },
    ];
    if (!ping || ping.ok !== 1) {
      return Response.json(
        { ok: false, error: "SELECT 1 returned unexpected shape" },
        { status: 503 },
      );
    }

    // 2. Did the build's `drizzle-kit push` actually create tables? A green
    //    Vercel build with an empty public schema means push exited without
    //    applying (usually a non-TTY prompt issue). Explicit tables-exist
    //    check catches that class.
    const rows = (await db.execute(
      sql`select count(*)::int as n from pg_catalog.pg_tables where schemaname = 'public'`,
    )) as unknown as [{ n: number }];
    const tableCount = rows?.[0]?.n ?? 0;
    if (tableCount === 0) {
      return Response.json(
        {
          ok: false,
          error:
            "no tables in public schema — the build's `drizzle-kit push` " +
            "did not create any tables. Check the Vercel build log for the " +
            "push output.",
        },
        { status: 503 },
      );
    }

    return Response.json({ ok: true, tables: tableCount });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json({ ok: false, error: msg }, { status: 503 });
  }
}
