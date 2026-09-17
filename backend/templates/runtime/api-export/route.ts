/**
 * GET /api/export/[entity] — streams a CSV of an entity's rows.
 * `[entity]` is the table name (e.g. "customers"). Forge runtime — do not remove.
 *
 * WHO MAY DOWNLOAD IT. This endpoint used to answer anybody. No session, no
 * role, `db.select()` — every row of any table, `users.password` with them,
 * to whoever knew the URL. The app already projects what it needs to answer
 * the question properly and this never read either file:
 *
 *   * `ENTITY_ACCESS` (src/lib/entity-access.ts) — the roles that may READ
 *     each entity, derived from the pages that bind it. `*` in the read list
 *     means a public page reads it, so an anonymous caller may too; an entity
 *     absent from the map is open to any signed-in role, which is that file's
 *     own stated rule and not a decision taken here.
 *   * `SENSITIVE_COLUMNS` (src/lib/sensitive-columns.ts) — the columns the
 *     data engine masks. §42 names EXPORTS as a place those values must not
 *     surface, so they are left out of the file altogether rather than
 *     masked: a column of `****` cannot be read, cannot be imported and
 *     cannot be explained.
 *
 * Beside the declared ones there is a floor that needs no Blueprint: nothing
 * the application AUTHENTICATES with is ever written to a spreadsheet. The
 * platform's own `users` table is not a declared entity, so no projection
 * covers its password column — and an export that carries password hashes is
 * the worst thing this route could do.
 *
 * The columns are named as the schema names them, which is what the Forge
 * import reads back, so a file that comes out here can go back in.
 */
import { db } from "@/db";
import * as schema from "@/db/schema";
import { getTableName, getTableColumns, is, Table } from "drizzle-orm";
import { auth } from "@/auth";

export const runtime = "nodejs";

/** Past this, the file says it holds the first N rows rather than pretending
 *  to be the whole table. */
const MAX_ROWS = 100_000;

/** Columns no export carries, whatever the Blueprint says, because the app
 *  authenticates with them. Matched on the normalised name so
 *  `password_hash`, `passwordHash` and `hashedPassword` are all covered. */
const CREDENTIAL = /(password|passwd|secret|token|apikey|salt|hash)/;

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

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

/** The read rule for a table, or null when nothing declares one. */
async function readers(table: string): Promise<string[] | null> {
  try {
    const mod: any = await import("@/lib/entity-access");
    const access = mod?.ENTITY_ACCESS ?? {};
    const entry = access[table] ?? access[table.toLowerCase()];
    const list = entry?.read;
    return Array.isArray(list) ? list.map(String) : null;
  } catch {
    // No projection in this app (older build): fall back to "signed in".
    return null;
  }
}

/** Declared sensitive columns for a table, by their normalised names. */
async function sensitive(table: string): Promise<Set<string>> {
  try {
    const mod: any = await import("@/lib/sensitive-columns");
    const bag = mod?.SENSITIVE_COLUMNS ?? {};
    const out = new Set<string>();
    for (const [entity, cols] of Object.entries(bag as Record<string, object>)) {
      // The map is keyed by entity name, the URL by table name; a Forge table
      // is the entity's name in snake_case, so compare on the normalised form
      // and take any entity whose columns belong to this table.
      if (norm(entity) !== norm(table) && norm(entity) + "s" !== norm(table)) continue;
      for (const col of Object.keys(cols ?? {})) out.add(norm(col));
    }
    return out;
  } catch {
    return new Set<string>();
  }
}

function cell(v: unknown): string {
  if (v == null) return "";
  const s = v instanceof Date ? v.toISOString() : typeof v === "object" ? JSON.stringify(v) : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function toCsv(cols: string[], rows: Record<string, unknown>[]): string {
  // Headers even with no rows: an empty table and a broken export are
  // different things and must not look the same.
  const head = cols.join(",");
  const body = rows.map((r) => cols.map((c) => cell(r[c])).join(",")).join("\n");
  return rows.length ? `${head}\n${body}\n` : `${head}\n`;
}

export async function GET(_req: Request, { params }: { params: Promise<{ entity: string }> }): Promise<Response> {
  const { entity } = await params;
  const table = resolveTable(entity);
  if (!table) return new Response(`Unknown entity: ${entity}`, { status: 404 });
  const name = getTableName(table);

  // ── who is asking ──────────────────────────────────────────────────────
  const allowed = await readers(name);
  const isPublic = allowed?.includes("*") ?? false;
  let role: string | null = null;
  if (!isPublic) {
    let session: any = null;
    try {
      session = await auth();
    } catch {
      session = null;
    }
    const user = session?.user as { role?: string } | undefined;
    if (!user) {
      return new Response("Sign in to export this data.", { status: 401 });
    }
    role = user.role ? String(user.role) : null;
    // A declared read list is the answer; no list means any signed-in role,
    // which is entity-access.ts's own rule for an entity it does not name.
    if (allowed && allowed.length > 0 && !(role && allowed.includes(role))) {
      return new Response(
        `Your role does not have read access to ${name}.`,
        { status: 403 },
      );
    }
  }

  // ── what the file may carry ────────────────────────────────────────────
  let columns: string[] = [];
  try {
    columns = Object.keys(getTableColumns(table));
  } catch {
    return new Response(`Cannot read the shape of ${name}`, { status: 500 });
  }
  const declaredSensitive = await sensitive(name);
  const withheld: string[] = [];
  const carry = columns.filter((c) => {
    if (declaredSensitive.has(norm(c)) || CREDENTIAL.test(norm(c))) {
      withheld.push(c);
      return false;
    }
    return true;
  });
  if (!carry.length) {
    return new Response(
      `Every column of ${name} holds a sensitive or credential value, so there is nothing an export may carry.`,
      { status: 403 },
    );
  }

  try {
    const rows = (await db.select().from(table).limit(MAX_ROWS)) as Record<string, unknown>[];
    const csv = toCsv(carry, rows);
    const headers: Record<string, string> = {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${name}.csv"`,
      "Cache-Control": "no-store",
    };
    // Said in a header rather than in the file: a comment row would break
    // every spreadsheet that opens it.
    if (withheld.length) headers["X-Forge-Withheld-Columns"] = withheld.join(",");
    if (rows.length >= MAX_ROWS) headers["X-Forge-Truncated"] = String(MAX_ROWS);
    return new Response(csv, { headers });
  } catch (err) {
    console.error("[api/export]", err);
    return new Response(`Export failed: ${String(err)}`, { status: 500 });
  }
}
