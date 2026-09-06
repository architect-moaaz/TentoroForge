/**
 * Database seed — deterministic, emitted by the Forge runtime injector.
 *
 * Every generated app needs (1) a login account or it's unusable, and (2) some
 * demo rows or its list/calendar/board pages render empty. This file provides both,
 * independent of any LLM step, so a fresh app is loginable and demoable out of the box.
 *
 *   1. Admin user — bcrypt-hashed with the same algorithm auth.ts verifies.
 *   2. Demo data — best-effort from contracts/seed-plan.json, in table order,
 *      coercing ISO dates and resolving foreign keys to already-inserted ids.
 *
 * Idempotent: the admin upserts on email; each domain table is skipped when it
 * already has rows. Run via `npx tsx src/db/seed.ts` (start.sh does this).
 */
import bcrypt from "bcryptjs";
import { sql, eq, getTableColumns } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { db } from "./index";
import * as schema from "./schema";

const ADMIN_EMAIL = process.env.SEED_ADMIN_EMAIL || "admin@example.com";
// Deterministic admin PK: reseeds/redeploys keep the same admin id, so rows
// FK-ing the admin (ownerId, createdBy) survive a reseed without dangling.
const ADMIN_UUID = "a0000000-0000-4000-8000-0000000000ad";
const ADMIN_PASSWORD = process.env.SEED_ADMIN_PASSWORD || "admin1234";
const ISO = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

// The LLM commonly emits placeholder id tokens ("uuid-1", "member-3", "id_7") for
// PKs and cross-row FK references instead of real UUIDs. Inserted verbatim they
// throw `invalid input syntax for type uuid`, so every row fails and the app has
// NO data. We mint a stable real UUID per token (shared across all tables, so a
// child's FK token resolves to the exact parent PK that was minted earlier).
const tokenMap: Record<string, string> = {};
const mintToken = (tok: string): string => (tokenMap[tok] ??= randomUUID());

/** Naive singular↔plural helper — enough to bridge the seed-plan naming
 *  gap (planner emits `MrrEvent`, drizzle exports `mrr_events`). Not a
 *  full inflection library — we only need bidirectional match. */
function inflections(s: string): string[] {
  const out = new Set<string>([s]);
  // Add plural form of a singular
  if (s.endsWith("y") && !/[aeiou]y$/.test(s)) out.add(s.slice(0, -1) + "ies");
  else if (/(s|x|z|ch|sh)$/.test(s)) out.add(s + "es");
  else out.add(s + "s");
  // Add singular form of a plural
  if (s.endsWith("ies") && s.length > 3) out.add(s.slice(0, -3) + "y");
  if (s.endsWith("es") && s.length > 2) out.add(s.slice(0, -2));
  if (s.endsWith("s") && !s.endsWith("ss")) out.add(s.slice(0, -1));
  return [...out];
}

/** Resolve a seed-plan table name to its Drizzle table export.
 *  Handles three sources of drift: (1) snake_case plan vs camelCase
 *  exports (via `norm` — strip non-alphanumerics + lowercase),
 *  (2) singular plan names (`Customer`) vs plural exports
 *  (`customers`) — the planner emits entity names, drizzle emits table
 *  names, and they disagree, and (3) exact-match on the name as
 *  provided. Return null when nothing matches so the caller can skip.
 */
function tableFor(name: string): any {
  const s = schema as Record<string, any>;
  if (s[name] && typeof s[name] === "object") return s[name];
  const wanted = new Set(inflections(norm(name)));
  for (const k of Object.keys(s)) {
    if (!s[k] || typeof s[k] !== "object") continue;
    if (wanted.has(norm(k))) return s[k];
  }
  return null;
}

/** Build a minimal insert row for `table`: fill every NOT NULL column that has
 *  no DB default with a type-appropriate placeholder (uuid→randomUUID, text→
 *  "Default <label>", number→0, bool→false, date→now). Columns WITH a default are
 *  omitted so Postgres fills them. Best-effort — used to satisfy a required-FK
 *  parent (e.g. a `workspaces` row that `users.workspace_id` points at). */
function minimalRow(
  table: any,
  label: string,
  overrides: Record<string, unknown> = {},
  skipFk = false,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...overrides };
  let cols: Record<string, any> = {};
  try { cols = getTableColumns(table); } catch { return out; }
  for (const [key, col] of Object.entries(cols)) {
    if (key in out || key === "id") continue;
    if (!col?.notNull || col?.hasDefault) continue;
    // FK-ish columns are resolved separately (parent must exist first); a random
    // uuid here would violate the reference. skipFk=true for the row being seeded.
    if (skipFk && /Id$/.test(key)) continue;
    const ct = String(col?.columnType ?? "").toLowerCase();
    const dt = String(col?.dataType ?? "").toLowerCase();
    if (ct.includes("uuid")) out[key] = randomUUID();
    else if (dt === "number") out[key] = 0;
    else if (dt === "boolean") out[key] = false;
    else if (dt === "date") out[key] = new Date();
    else if (dt === "json") out[key] = {};
    else if (/name|title|label|slug/i.test(key)) out[key] = label; // name-like → the label
    else out[key] = `Default ${label}`;
  }
  return out;
}

/** Satisfy required foreign keys on `table` before inserting `row`.
 *  For each NOT NULL, no-default, FK-style column (name ends in `Id`, e.g.
 *  `workspaceId`), find the parent table by convention (workspace→workspaces),
 *  reuse an existing parent row or create a minimal one, and set the id on `row`.
 *  Fixes multi-tenant schemas where the admin insert would otherwise fail the
 *  `users.workspace_id` NOT NULL constraint. Never throws. */
async function resolveRequiredFks(table: any, row: Record<string, unknown>): Promise<void> {
  let cols: Record<string, any> = {};
  try { cols = getTableColumns(table); } catch { return; }
  for (const [key, col] of Object.entries(cols)) {
    if (key === "id" || key in row) continue;
    if (!col?.notNull || col?.hasDefault) continue;
    if (!/Id$/.test(key)) continue; // FK-ish columns only
    const base = key.replace(/Id$/, "");
    const parent = tableFor(base) || tableFor(base + "s") || tableFor(base + "es");
    if (!parent) continue;
    let pid: unknown = null;
    try {
      const existing: any[] = await db.select().from(parent).limit(1);
      if (existing.length && existing[0]?.id != null) pid = existing[0].id;
    } catch { /* fall through to insert */ }
    if (pid == null) {
      try {
        const r: any[] = await db.insert(parent).values(minimalRow(parent, base)).returning();
        pid = r?.[0]?.id ?? null;
      } catch (e) {
        console.warn(`seed: could not create default ${base}:`, e);
      }
    }
    if (pid != null) row[key] = pid;
  }
}

async function seedAdmin(): Promise<string | null> {
  const users = tableFor("users");
  if (!users) {
    console.log("ℹ️  no users table — skipping admin seed");
    return null;
  }
  const password = await bcrypt.hash(ADMIN_PASSWORD, 12);
  const row: Record<string, unknown> = { email: ADMIN_EMAIL, password };
  // Pin the admin id when the PK is a uuid column (serial int PKs keep the
  // DB default — a uuid literal would fail the insert).
  const idCol: any = (users as any).id;
  if (idCol && /uuid/i.test(String(idCol.columnType ?? ""))) row.id = ADMIN_UUID;
  if ("name" in users) row.name = "Admin";
  if ("isActive" in users) row.isActive = true;
  if ("role" in users) row.role = "admin";
  // Satisfy any NOT NULL foreign keys (e.g. workspace_id in multi-tenant schemas)
  // so the admin insert doesn't fail the constraint and leave the app login-less.
  await resolveRequiredFks(users, row);
  // Backstop: fill any remaining NOT NULL, no-default, non-FK column the schema
  // added (e.g. full_name / displayName) so the insert never fails a constraint.
  Object.assign(row, minimalRow(users, "Admin", row, /* skipFk */ true));
  try {
    const r = await db.insert(users).values(row).onConflictDoNothing({ target: users.email }).returning();
    if (r.length) {
      console.log(`✅ admin user: ${ADMIN_EMAIL} (password: ${ADMIN_PASSWORD})`);
      return r[0]?.id ? String(r[0].id) : null;
    }
    // Existed already — look up its id so seedDomain can populate the users FK
    // pool. Without this, downstream tables with a NOT NULL user_id FK insert
    // dangling ids on re-runs and Postgres rejects them silently (SEED MISMATCH).
    console.log(`ℹ️  admin ${ADMIN_EMAIL} already exists`);
    try {
      const existing: any[] = await db
        .select({ id: (users as any).id })
        .from(users as any)
        .where(eq((users as any).email, ADMIN_EMAIL));
      return existing[0]?.id ? String(existing[0].id) : null;
    } catch {
      return null;
    }
  } catch (e) {
    console.warn("admin seed failed:", e);
    return null;
  }
}

function prepRow(table: any, row: Record<string, unknown>, ids: Record<string, string[]>, i: number): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  // Map each Drizzle property by its normalized name so seed rows keyed in
  // snake_case (e.g. "unit_cost") resolve to the camelCase column ("unitCost").
  // Without this, mismatched keys are dropped and NOT NULL columns fail insert.
  const propByNorm: Record<string, string> = {};
  for (const key of Object.keys(table)) propByNorm[norm(key)] = key;

  for (const [k, v] of Object.entries(row)) {
    const prop = (k in table) ? k : propByNorm[norm(k)];
    if (!prop) continue;
    let val: unknown = v;
    if (typeof val === "string") {
      // Resolve seed-plan FK placeholders like "ref:landlords[0]" to the real
      // id of the already-inserted parent row. Unresolvable refs fall through
      // as null so the FK-fill loop below can pick a valid parent id.
      const m = val.match(/^ref:(\w+)\[(\d+)\]$/);
      const isId = prop === "id" || /(Id|_id)$/.test(prop);
      if (m) {
        const pool = ids[norm(m[1])] || ids[norm(m[1]) + "s"] || ids[norm(m[1]) + "es"];
        val = pool && pool.length ? pool[Number(m[2]) % pool.length] : null;
      } else if (isId && !UUID_RE.test(val)) {
        // Placeholder id token. A PK mints a fresh UUID; an FK resolves ONLY to a
        // parent token already minted (else null → the FK-fill loop picks a valid
        // parent, so we never insert a dangling reference).
        val = prop === "id" ? mintToken(val) : (val in tokenMap ? tokenMap[val] : null);
      } else if (ISO.test(val)) {
        // WHAT THE DRIVER WILL BIND, by drizzle's own dataType. `timestamp()`
        // is dataType "date" and takes a Date; `date()` in string mode is
        // dataType "string" and takes "YYYY-MM-DD" — handed a Date it threw
        // from Buffer.byteLength and every member and bill failed to seed.
        const target = (table as any)[prop];
        const dt = String(target?.dataType ?? "").toLowerCase();
        const ct = String(target?.columnType ?? "").toLowerCase();
        if (dt === "date") {
          const d = new Date(val);
          if (!isNaN(d.getTime())) val = d;
        } else if (dt === "string" && ct.includes("date") && !ct.includes("time")) {
          val = String(val).slice(0, 10);
        }
      }
    }
    out[prop] = val;
  }
  // Fill foreign keys (xxxId / xxx_id) with a real id from the referenced table.
  for (const k of Object.keys(table)) {
    if (!/(Id|_id)$/.test(k) || out[k] != null) continue;
    const stem = norm(k.replace(/(_id|Id)$/, ""));
    const pool = ids[stem] || ids[stem + "s"] || ids[stem + "es"];
    if (pool && pool.length) out[k] = pool[i % pool.length];
  }
  return out;
}

async function seedDomain(adminId: string | null): Promise<void> {
  // TWO PRODUCERS, ONE READER. The legacy pipeline wrote contracts/seed-plan.json;
  // the Blueprint projection writes src/db/seed.json as { table: rows[] } and
  // this read only the first, so every Blueprint-built app seeded nothing but
  // the admin. The projection's file is read when the plan is absent, its
  // tables seeded in rounds so a child whose parent has not been inserted yet
  // is retried after the parent — the file's keys are alphabetical, not
  // dependency-ordered.
  const planPath = path.join(process.cwd(), "contracts", "seed-plan.json");
  const seedPath = path.join(process.cwd(), "src", "db", "seed.json");
  let plan: any;
  if (fs.existsSync(planPath)) {
    try { plan = JSON.parse(fs.readFileSync(planPath, "utf8")); } catch { return; }
  } else if (fs.existsSync(seedPath)) {
    try {
      const bag = JSON.parse(fs.readFileSync(seedPath, "utf8")) as Record<string, unknown[]>;
      plan = { tables: Object.keys(bag).map((name, i) => ({ name, order: i, seed_data: bag[name] })) };
    } catch { return; }
  } else {
    return;
  }
  const tables = (plan.tables || []).slice().sort((a: any, b: any) => (a.order ?? 0) - (b.order ?? 0));
  const ids: Record<string, string[]> = {};
  // Pre-populate the users pool with the admin id so any NOT NULL user_id FK
  // on downstream tables resolves to a real row. The synthesizer no longer
  // mints dangling UUIDs for user FKs; without this pre-population, prepRow
  // has no id to fill in and Postgres rejects every child insert (silent
  // SEED MISMATCH: <table> planned N inserted 0).
  if (adminId) {
    ids["users"] = [adminId];
    ids["user"] = [adminId];
  }
  const seedOne = async (t: any): Promise<number | null> => {
    const table = tableFor(t.name);
    if (!table) return null;
    try {
      const [{ c }] = await db.select({ c: sql<number>`count(*)::int` }).from(table);
      if (c > 0) {
        // Already populated — load its ids so child tables can still resolve
        // FK refs to it on a re-run (otherwise ref:parent[i] can't resolve).
        try {
          const existing: any[] = await db.select({ id: table.id }).from(table);
          ids[norm(t.name)] = existing.map((r) => String(r.id));
        } catch {
          /* table has no simple id column — leave pool empty */
        }
        console.log(`ℹ️  ${t.name} already has ${c} rows — skipping insert`);
        return null;
      }
    } catch {
      /* count failed (table may differ) — attempt insert anyway */
    }
    // Demo rows live in a top-level dict on the plan, keyed by table name. The
    // generator names that dict inconsistently — "sample_data" on some runs,
    // "seed_data" on others — so accept both. (t.seed_data is a legacy
    // per-table field, kept only as a last resort.)
    const isDict = (o: unknown): o is Record<string, unknown[]> =>
      !!o && typeof o === "object" && !Array.isArray(o);
    const bag = (isDict(plan.sample_data) ? plan.sample_data
              : isDict(plan.seed_data) ? plan.seed_data
              : {}) as Record<string, unknown[]>;
    const rows: Record<string, unknown>[] =
      (t.seed_data as Record<string, unknown>[] | undefined) ||
      (bag[t.name] as Record<string, unknown>[] | undefined) || [];
    const got: string[] = [];
    let firstErr: string | null = null;
    for (let i = 0; i < rows.length; i++) {
      try {
        const values = prepRow(table, rows[i], ids, i);
        const res: any = await db.insert(table).values(values).returning();
        const id = res?.[0]?.id;
        if (id != null) got.push(String(id));
      } catch (e: any) {
        // Capture the FIRST error per table so a SEED MISMATCH tells us WHY
        // (bad FK, NOT-NULL violation, type mismatch). Without this the loop
        // silently swallowed every error and we shipped empty tables.
        if (firstErr === null) firstErr = String(e?.message || e).slice(0, 500);
        /* skip a bad row, keep going */
      }
    }
    ids[norm(t.name)] = got;
    // Loud-on-empty: planned rows existed but NONE inserted → a real seed bug
    // (bad FK, type mismatch, wrong table). Emit a greppable marker so the
    // seed-smoke gate catches it; stay non-fatal so boot still completes.
    if (rows.length > 0 && got.length === 0) {
      // Reported by the caller once the rounds are over; a parent that
      // simply has not been seeded yet is not a mismatch. The first error
      // travels with the table so the final report can say WHY.
      (t as any).__firstErr = firstErr;
      return 0;
    }
    console.log(`✅ seeded ${got.length}/${rows.length} ${t.name}`);
    return got.length;
  };
  let pending: any[] = tables;
  for (let round = 0; round < 6 && pending.length > 0; round++) {
    const next: any[] = [];
    for (const t of pending) {
      const n = await seedOne(t);
      if (n === 0) next.push(t);
    }
    if (next.length === pending.length) {
      for (const t of next) {
        console.error(`❌ SEED MISMATCH: ${t.name} planned rows inserted 0`);
        if ((t as any).__firstErr) console.error(`   ↳ first row error: ${(t as any).__firstErr}`);
      }
      break;
    }
    pending = next;
  }
}

/**
 * Compute a stable fingerprint of the drizzle schema shape — one hash
 * over every exported table's canonical column list. Insensitive to
 * whitespace, sensitive to (a) columns added/removed and (b) column
 * name changes. Type / FK-target changes are NOT captured here (would
 * require reflecting drizzle internals) but the column-set change is
 * usually enough to catch a shape drift that would invalidate the
 * existing rows. Deterministic across runs on the same schema.
 */
function computeSchemaFingerprint(): string {
  const parts: string[] = [];
  const entries = Object.entries(schema as Record<string, any>)
    .filter(([, v]) => v && typeof v === "object")
    .sort(([a], [b]) => a.localeCompare(b));
  for (const [name, table] of entries) {
    let cols: string[] = [];
    try { cols = Object.keys(getTableColumns(table)).sort(); }
    catch { continue; }
    if (cols.length === 0) continue;
    parts.push(`${name}:${cols.join(",")}`);
  }
  // Node has crypto — small dependency-free hash: FNV-1a 32-bit hex.
  // Collision risk is negligible for the number of shapes an app can
  // realistically take.
  const s = parts.join("|");
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

/**
 * Robust idempotency gate — returns true when the seed should be
 * SKIPPED: the drizzle shape matches the last-seeded fingerprint AND
 * at least one domain table has rows. On any error (missing table,
 * permission issue, first-ever run) returns false so the seed runs.
 *
 * Uses raw SQL so a missing ``_forge_seed_meta`` table doesn't crash
 * the driver — the CREATE-IF-NOT-EXISTS guarantees the table exists
 * before we query it.
 */
async function shouldSkipSeed(currentFingerprint: string): Promise<boolean> {
  try {
    await db.execute(sql`
      CREATE TABLE IF NOT EXISTS _forge_seed_meta (
        id INT PRIMARY KEY,
        fingerprint TEXT NOT NULL,
        row_probe_ok BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);
    const res: any = await db.execute(
      sql`SELECT fingerprint, row_probe_ok FROM _forge_seed_meta WHERE id = 1 LIMIT 1`
    );
    const rows: any[] = (res as any).rows ?? res ?? [];
    if (!rows.length) return false;
    const persisted = String(rows[0].fingerprint || "").toLowerCase();
    if (persisted !== currentFingerprint.toLowerCase()) return false;
    // Shape unchanged — verify at least one domain table has rows.
    // We probe up to 4 tables (skipping _forge_seed_meta itself and any
    // auth table which is upserted every run anyway) — if any is
    // non-empty, seed is valid. Use raw SQL so a missing table becomes
    // a soft "false" rather than a hard error.
    const tables = Object.entries(schema as Record<string, any>)
      .filter(([n, v]) => v && typeof v === "object"
                            && !n.startsWith("_forge_")
                            && !/^(user|users|account|accounts|auth)$/i.test(n))
      .slice(0, 4);
    for (const [name] of tables) {
      try {
        const probe: any = await db.execute(
          sql.raw(`SELECT 1 FROM ${name} LIMIT 1`)
        );
        const probeRows: any[] = (probe as any).rows ?? probe ?? [];
        if (probeRows.length > 0) return true;
      } catch { /* table missing / renamed — treat as "no data", let seed run */ }
    }
    return false;
  } catch (e) {
    console.log("[seed] idempotency probe failed, will run seed:", e);
    return false;
  }
}

async function recordSeedFingerprint(fp: string): Promise<void> {
  try {
    await db.execute(sql`
      INSERT INTO _forge_seed_meta (id, fingerprint, row_probe_ok, updated_at)
      VALUES (1, ${fp}, TRUE, NOW())
      ON CONFLICT (id) DO UPDATE SET
        fingerprint = EXCLUDED.fingerprint,
        row_probe_ok = TRUE,
        updated_at = NOW()
    `);
  } catch (e) {
    console.log("[seed] fingerprint record failed:", e);
  }
}

async function main(): Promise<void> {
  // Idempotency gate — skip the whole seed when the schema shape is
  // unchanged from the last successful seed AND at least one domain
  // table has rows. Override with FORCE_SEED=1 for a manual reseed
  // (useful after a data wipe or when developing seed content).
  if (process.env.FORGE_KEEP_DB_STATE === "1"
      && !/^(1|true|yes)$/i.test(String(process.env.FORCE_SEED || ""))) {
    console.log("[seed] FORGE_KEEP_DB_STATE=1 — preserving existing data, skipping reseed");
    return;
  }
  const currentFp = computeSchemaFingerprint();
  const forceSeed = /^(1|true|yes)$/i.test(String(process.env.FORCE_SEED || ""));
  if (!forceSeed && await shouldSkipSeed(currentFp)) {
    console.log(
      `[seed] shape unchanged (fingerprint=${currentFp}) + data present — skipping. ` +
      `Set FORCE_SEED=1 to reseed.`
    );
    return;
  }
  const adminId = await seedAdmin();
  await seedDomain(adminId);
  await recordSeedFingerprint(currentFp);
  console.log(`[seed] complete — fingerprint recorded (${currentFp}).`);
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("Seed failed:", err);
    process.exit(1);
  });
