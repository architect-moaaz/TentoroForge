/**
 * Database seed — deterministic, emitted by the Forge runtime injector.
 *
 * Every generated app needs (1) a login account or it's unusable, and (2) some
 * demo rows or its list/calendar/board pages render empty. This file provides both,
 * independent of any LLM step, so a fresh app is loginable and demoable out of the box.
 *
 *   1. Admin user — bcrypt-hashed with the same algorithm auth.ts verifies.
 *   2. Imported data — the owner's OWN records, from src/db/imports/*.json
 *      (written by services.smith.data_import when they load a spreadsheet).
 *   3. Demo data — best-effort from contracts/seed-plan.json, in table order,
 *      coercing ISO dates and resolving foreign keys to already-inserted ids.
 *
 * WHY THE IMPORTS ARE HERE AND NOT IN A SCRIPT OF THEIR OWN. This is the only
 * route in the product that writes rows, it is already run by start.sh, the
 * preview manager and every publish, and it holds every hard-won rule about
 * how a row actually reaches Postgres (tableFor, prepRow, _driverSafeDates,
 * FK resolution). A second inserter would be a second copy of all of it.
 *
 * They are applied BEFORE the demo data and before both skip gates: an owner's
 * real records must land in a reused database, and once they have, the demo
 * pass leaves their table alone — so an app with four hundred real customers
 * never shows "Customer 1". Applied at most once each, by import id, so a
 * redeploy does not load the same spreadsheet twice.
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
// Who signs in (projected from the Blueprint by account_model). Relative, not
// `@/`: the seed runs under tsx, outside Next's path aliases.
import { ACCOUNT, ADMIN_ROLE, SIGNUP_ROLE } from "../lib/account";
import { accountTable } from "../lib/account-table";

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

/**
 * NO SEEDED ROW CARRIES A READABLE CREDENTIAL, and every one that needs a
 * credential column gets a valid value.
 *
 * Both halves were broken and each broke something different. The plan's value
 * for a password column is either a plaintext ("Passw0rd!") or a label
 * ("Password Hash 1"), and it was inserted verbatim: `auth.ts` bcrypt-compares
 * what it finds, so the account existed and NOBODY COULD SIGN INTO IT — while
 * a plaintext password sat in the database and in the committed seed file
 * (§42). Meanwhile a plan that named the column `passwordHash` matched no
 * column on the shipped table (the platform calls it `password`), so the key
 * was dropped, the NOT NULL insert failed, and the whole staff list seeded
 * nothing at all.
 *
 * So the column is filled here, always, with the bcrypt hash of a fresh random
 * UUID: a valid hash whose input nobody holds. The row exists as data — a
 * staff list renders, a FK to it resolves — and the account cannot be signed
 * into, which is the honest state of an account nobody was given. The ways in
 * are `admin@example.com` and an invited account (`seedAccounts`), and neither
 * comes through here.
 *
 * WHICH COLUMNS. Any whose name contains "password". That is the whole rule:
 * such a column is a credential in every application there is, and a narrower
 * question than the author-side refusal (`_CREDENTIAL_COLUMNS` in
 * functional_completeness.py) deliberately — that one may over-reach onto
 * `salt` because a workflow has no business writing it either, while this
 * transforms a value in ANY table, where `salt` is a real column in a recipe
 * app and would be corrupted.
 */
/** Tables whose planned rows all failed this run (see seedDomain). */
let SEED_MISMATCHES = 0;

const _isCredentialColumn = (key: string) => norm(key).includes("password");

/** A valid bcrypt hash whose input nobody holds, so the column is filled and
 *  the account cannot be signed into. hashSync because both callers are
 *  synchronous, and both run a handful of times per build. */
const _unusableCredential = () => bcrypt.hashSync(randomUUID(), 10);

function _unusableCredentials(table: any, out: Record<string, unknown>): void {
  for (const key of Object.keys(table)) {
    // UNCONDITIONALLY, unlike the fill in `minimalRow`: here the value came
    // from the plan, and the whole point is that it must not land.
    if (_isCredentialColumn(key)) out[key] = _unusableCredential();
  }
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
    // A required credential column got "Default Admin", which `auth.ts`
    // bcrypt-compares and no password ever matches. Filled with a hash nobody
    // holds instead — and only when absent, because `seedAdmin` and
    // `seedAccounts` pass the hash they mean in as an override.
    if (_isCredentialColumn(key)) out[key] = _unusableCredential();
    else if (ct.includes("uuid")) out[key] = randomUUID();
    else if (dt === "number") out[key] = 0;
    else if (dt === "boolean") out[key] = false;
    else if (dt === "date") out[key] = new Date();
    // A string-mode `date()` / `timestamp()` column (dataType "string") cannot
    // take "Default label" ("invalid input syntax for date") NOR a Date (see
    // _driverSafeDates) — give it a valid calendar date / ISO datetime string.
    else if (dt === "string" && /date|time/.test(ct)) {
      out[key] = /time/.test(ct) ? new Date().toISOString() : new Date().toISOString().slice(0, 10);
    }
    else if (dt === "json") out[key] = {};
    else if (/name|title|label|slug/i.test(key)) out[key] = label; // name-like → the label
    else out[key] = `Default ${label}`;
  }
  _driverSafeDates(table, out);
  return out;
}

/**
 * Final safety net for the seed's direct drizzle inserts: postgres-js cannot
 * serialize a Date for a STRING-typed column and throws, which seedOne swallows
 * per-row — so a whole app can deploy with an EMPTY database and a green build.
 * Coerce any Date destined for a string column to text (mirrors the workflow
 * and data-engine write paths, DEFECT-DEPLOY-CREATE / DEFECT-DEPLOY-SEED).
 */
function _driverSafeDates(table: any, row: Record<string, unknown>): void {
  for (const [k, v] of Object.entries(row)) {
    if (!(v instanceof Date)) continue;
    const col = table?.[k];
    if (!col || String(col.dataType).toLowerCase() !== "string") continue;
    const ct = String(col.columnType || "");
    row[k] = /timestamp|date|time/i.test(ct)
      ? (/time/i.test(ct) ? v.toISOString() : v.toISOString().slice(0, 10))
      : v.toISOString();
  }
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

/**
 * EVERY SEEDED LOGIN IS A PERSON TOO. When the application has an account
 * entity, each login has its row — the same id — as signup gives a new
 * person; otherwise "my Member" was empty for the admin and every invited
 * login, and whatever they did could not be tied to them.
 */
async function ensureAccountRow(id: string | null, email: string, name: string): Promise<void> {
  if (!ACCOUNT || !accountTable || !id) return;
  const row: Record<string, unknown> = { id };
  for (const f of ACCOUNT.fields) if (f.kind === "email" && f.name in accountTable) row[f.name] = email;
  if (ACCOUNT.labelField && ACCOUNT.labelField in accountTable) row[ACCOUNT.labelField] = name;
  await resolveRequiredFks(accountTable, row);
  Object.assign(row, minimalRow(accountTable, name, row, /* skipFk */ true));
  try {
    await db.insert(accountTable).values(row as any).onConflictDoNothing();
  } catch (err) {
    console.warn(`⚠️  ${ACCOUNT.entity} for ${email} not seeded:`, err);
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
  // THE ADMIN HOLDS THE APPLICATION'S WIDEST ROLE (ADMIN_ROLE, projected from
  // the Blueprint). It held the sign-up role, so 0l133sp2's admin was a Member
  // and could not open the verification queue it was told about.
  if ("role" in users) row.role = ADMIN_ROLE ?? "admin";
  // No role column: the session role is `accountType`. Without one the admin
  // held the platform's "user", which no page or workflow of the app names,
  // and every role-gated workflow refused them.
  else if ("accountType" in users && (ADMIN_ROLE || SIGNUP_ROLE)) row.accountType = ADMIN_ROLE ?? SIGNUP_ROLE;
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
    // AND ITS ROLE IS PUT RIGHT. An admin seeded before the Blueprint said
    // which role opens the back office kept the sign-up role for good:
    // `onConflictDoNothing` never revisits a row. 0l133sp2's admin stayed a
    // Member, so the verification queue answered 403 and the "awaiting KYC"
    // notification addressed to Admin reached nobody. The role is the
    // application's to decide, not a fact about that row, so every seed
    // states it again — and nothing else about the account is touched.
    const roleColumn = "role" in users ? "role" : "accountType" in users ? "accountType" : null;
    const wanted = roleColumn === "role" ? ADMIN_ROLE ?? "admin" : ADMIN_ROLE ?? SIGNUP_ROLE;
    if (roleColumn && wanted) {
      try {
        const [before] = await db.select().from(users as any)
          .where(eq((users as any).email, ADMIN_EMAIL));
        if (before && before[roleColumn] !== wanted) {
          await db.update(users as any).set({ [roleColumn]: wanted } as any)
            .where(eq((users as any).email, ADMIN_EMAIL));
          console.log(`✅ admin role: ${String(before[roleColumn] ?? "none")} → ${wanted}`);
        }
      } catch (e) {
        console.warn("admin role could not be confirmed:", e);
      }
    }
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

/** One roster entry as Smith writes it into src/db/accounts.json. */
type RosterEntry = {
  email?: string;
  name?: string;
  role?: string;
  status?: string;
  invite?: { issue?: string; tokenHash?: string; purpose?: string; expiresAt?: string } | null;
};

/** The people the owner asked to be able to log in, or [] when none. */
function accountRoster(): RosterEntry[] {
  const rosterPath = path.join(process.cwd(), "src", "db", "accounts.json");
  if (!fs.existsSync(rosterPath)) return [];
  try {
    const doc = JSON.parse(fs.readFileSync(rosterPath, "utf8"));
    const rows = Array.isArray(doc) ? doc : doc?.accounts;
    return Array.isArray(rows) ? (rows as RosterEntry[]) : [];
  } catch (e) {
    console.warn("[seed] accounts.json could not be read:", e);
    return [];
  }
}

/**
 * The people who log in, as the owner asked for them.
 *
 * WHY THE SEED AND NOT A DIRECT WRITE. An account has to survive a redeploy or
 * it is not an account: the database behind a generated app is rebuilt, reseeded
 * and republished, and anything inserted into it out of band is gone the next
 * time. The roster is a file in the project, so it is applied again on every
 * start — which is also why this runs beside `seedAdmin`, ABOVE the skip gates:
 * they preserve domain data, never the sign-in.
 *
 * NO PASSWORD PASSES THROUGH HERE. An account is created with a hash of a fresh
 * random UUID — a valid bcrypt hash whose input nobody holds, so the account
 * cannot be signed into — and inactive. What makes it usable is the person
 * opening their setup link and choosing a password, which the platform's own
 * /api/auth/set-password route hashes. Smith never sees a plaintext credential
 * and never writes a credential column.
 *
 * IDEMPOTENT ON THE ISSUE, not on the row. An invite row is found by its
 * `issue` — the id of that one issuance. Already there, the invite has been
 * applied and is left alone, whether or not it has been used; otherwise it is
 * new, and the account's password is cleared and the link opened. Without that,
 * every restart would re-open a spent link and clear a password the person had
 * already chosen.
 */
async function seedAccounts(): Promise<void> {
  const roster = accountRoster();
  if (!roster.length) return;
  const users = tableFor("users");
  if (!users) {
    console.log("\u2139\uFE0F  no users table \u2014 skipping the account roster");
    return;
  }
  const invites = tableFor("forgeInvites");
  for (const entry of roster) {
    const email = String(entry?.email || "").trim().toLowerCase();
    if (!email) continue;
    try {
      // REMOVED IS DEACTIVATED, NOT DELETED. `authorize` rejects a falsy
      // isActive, so the person can no longer sign in; the row stays because
      // every record they created points at it.
      if (String(entry.status || "active") === "removed") {
        if ("isActive" in users) {
          await db.update(users).set({ isActive: false } as any).where(eq((users as any).email, email));
        }
        // A pending link would set isActive back to true, so it is spent here.
        if (invites) {
          await db.update(invites).set({ usedAt: new Date() } as any)
            .where(eq((invites as any).email, email));
        }
        console.log(`\u2705 login deactivated: ${email}`);
        continue;
      }

      const row: Record<string, unknown> = { email, password: await bcrypt.hash(randomUUID(), 12) };
      if ("name" in users && entry.name) row.name = String(entry.name);
      if ("isActive" in users) row.isActive = false;
      // Whichever column auth.ts reads a role from: an explicit `role` when the
      // Blueprint added one, else the signup account type it falls back to.
      if (entry.role) {
        if ("role" in users) row.role = String(entry.role);
        else if ("accountType" in users) row.accountType = String(entry.role);
      }
      await resolveRequiredFks(users, row);
      Object.assign(row, minimalRow(users, String(entry.name || email), row, /* skipFk */ true));
      const created = await db.insert(users).values(row as any)
        .onConflictDoNothing({ target: (users as any).email }).returning();
      if (created[0]?.id) await ensureAccountRow(String(created[0].id), email, String(entry.name || email));

      const invite = entry.invite;
      const issue = String(invite?.issue || "");
      if (!invites || !invite || !issue || !invite.tokenHash || !invite.expiresAt) {
        if (created.length) console.log(`\u2705 login created: ${email}`);
        continue;
      }
      const [applied] = await db.select().from(invites)
        .where(eq((invites as any).issue, issue)).limit(1);
      if (applied) continue;                       // this issuance is already in

      await db.insert(invites).values({
        email,
        tokenHash: String(invite.tokenHash),
        issue,
        purpose: String(invite.purpose || "invite"),
        expiresAt: new Date(String(invite.expiresAt)),
        usedAt: null,
      } as any).onConflictDoUpdate({
        target: (invites as any).email,
        set: {
          tokenHash: String(invite.tokenHash), issue,
          purpose: String(invite.purpose || "invite"),
          expiresAt: new Date(String(invite.expiresAt)), usedAt: null,
        },
      });
      if (!created.length) {
        // An existing account with a new issuance: the old password stops
        // working now, which is what a reset means.
        const cleared: Record<string, unknown> = { password: await bcrypt.hash(randomUUID(), 12) };
        if ("isActive" in users) cleared.isActive = false;
        await db.update(users).set(cleared as any).where(eq((users as any).email, email));
      }
      console.log(`\u2705 login ${created.length ? "created" : "reset"}, awaiting its password: ${email}`);
    } catch (e) {
      console.warn(`[seed] account ${email} failed:`, e);
    }
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
    // DATE-TYPED COLUMN SAFETY. Synthesized data sometimes carries a label like
    // "Start Time 1" for what the schema made a `timestamp`/`date`; handed to a
    // date-mode column drizzle calls `.toISOString()` on that string and throws
    // ("value.toISOString is not a function"), so every row of the table fails
    // to seed. Coerce anything a date-ish column can't accept to a valid value:
    // a Date for date-mode, a YYYY-MM-DD / ISO string for string-mode.
    const tcol: any = (table as any)[prop];
    if (tcol) {
      const dt = String(tcol.dataType ?? "").toLowerCase();
      const ct = String(tcol.columnType ?? "").toLowerCase();
      if (dt === "date" || /timestamp|date|time/.test(ct)) {
        if (dt === "string") {
          const s = typeof val === "string" && /^\d{4}-\d{2}-\d{2}/.test(val) ? val : "";
          val = /time/.test(ct) && !/date/.test(ct)
            ? (s || new Date().toISOString())
            : (s ? s.slice(0, 10) : new Date().toISOString().slice(0, 10));
        } else if (!(val instanceof Date)) {
          const d = new Date(val as any);
          val = isNaN(d.getTime()) ? new Date() : d;
        }
      }
    }
    out[prop] = val;
  }
  // Fill foreign keys (xxxId / xxx_id) with a real id from the referenced table.
  // The parent pool is keyed by the inserted table's normalized name; a column's
  // stem is not always that name — `ownerId`/`createdBy` point at `users`, and
  // `veterinarianId` at `veterinarian_profiles` — so an exact stem lookup leaves
  // a NOT NULL uuid FK null and the whole row fails. Resolve in three passes.
  const singular = (s: string) => s.replace(/ies$/, "y").replace(/(ses|xes|zes|ches|shes)$/, (m) => m.slice(0, -2)).replace(/s$/, "");
  for (const k of Object.keys(table)) {
    if (!/(Id|_id)$/.test(k) || out[k] != null) continue;
    const stem = norm(k.replace(/(_id|Id)$/, ""));
    let pool = ids[stem] || ids[stem + "s"] || ids[stem + "es"];
    // 1. User-semantic FK names resolve to the always-seeded users pool. Match
    //    on the SUFFIX so a compound name works too — `petOwnerId` ends in
    //    `owner`, `assignedToId` in `assignedto`.
    if ((!pool || !pool.length) &&
        /(owner|creator|createdby|author|updatedby|modifiedby|assignee|assignedto|assignedby|reviewer|approver|manager|member|user|admin)$/.test(stem)) {
      pool = ids["users"] || ids["user"];
    }
    // 2. Fuzzy: a seeded pool whose (singularized) name the stem ends with, or
    //    which contains the stem — `rescheduledFromSlotId` → slots,
    //    `veterinarianId` → veterinarianProfiles, `availabilityId` →
    //    availabilities. Suffix-anchored so a compound FK still finds its table.
    if (!pool || !pool.length) {
      const kk = Object.keys(ids).find((p) => {
        if (!ids[p]?.length) return false;
        const sp = singular(p);
        return p.includes(stem) || stem.includes(p) || (sp.length >= 3 && stem.endsWith(sp));
      });
      if (kk) pool = ids[kk];
    }
    if (pool && pool.length) out[k] = pool[i % pool.length];
  }
  _unusableCredentials(table, out);
  _driverSafeDates(table, out);
  return out;
}

/**
 * The owner's own records, loaded from a spreadsheet.
 *
 * Each file is `{ import, table, rows[] }` — one per import, named by the
 * import's id, which is the content hash of the file they attached. The id is
 * the idempotency key: `_forge_import_log` remembers which have been applied,
 * so a redeploy, a reseed or a second boot does not give them every customer
 * twice.
 *
 * A row that Postgres refuses is reported and skipped — the rest of the file
 * still lands, and the count tells the owner (and the platform log) that some
 * did not. The rows were already coerced to the declared field types before
 * they were written, so a refusal here is a schema fact, not a value we could
 * have fixed by guessing.
 */
async function applyImports(): Promise<Set<string>> {
  const owned = new Set<string>();
  const dir = path.join(process.cwd(), "src", "db", "imports");
  if (!fs.existsSync(dir)) return owned;
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort();
  if (!files.length) return owned;

  try {
    await db.execute(sql`
      CREATE TABLE IF NOT EXISTS _forge_import_log (
        id TEXT PRIMARY KEY,
        table_name TEXT NOT NULL,
        rows_applied INT NOT NULL DEFAULT 0,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);
  } catch (e) {
    console.warn("[import] could not open the import log — skipping imports:", e);
    return owned;
  }

  for (const file of files) {
    let payload: { import?: string; table?: string; rows?: Record<string, unknown>[] };
    try {
      payload = JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"));
    } catch (e) {
      console.error(`❌ [import] ${file} is not readable JSON:`, e);
      continue;
    }
    const importId = String(payload.import || file.replace(/\.json$/, ""));
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    if (!payload.table || !rows.length) continue;

    try {
      const seen: any = await db.execute(
        sql`SELECT rows_applied FROM _forge_import_log WHERE id = ${importId} LIMIT 1`
      );
      const seenRows: any[] = (seen as any).rows ?? seen ?? [];
      if (seenRows.length) {
        console.log(`ℹ️  [import] ${importId} already applied (${seenRows[0].rows_applied} rows)`);
        owned.add(norm(String(payload.table)));
        continue;
      }
    } catch (e) {
      console.warn(`[import] ${importId}: could not read the log, skipping to be safe:`, e);
      continue;                 // NEVER load twice because a probe failed.
    }

    owned.add(norm(String(payload.table)));
    const table = tableFor(String(payload.table));
    if (!table) {
      console.error(`❌ [import] ${importId}: no table named ${payload.table} — the ` +
                    `schema has moved on since the file was written. Nothing loaded.`);
      continue;
    }
    let applied = 0;
    let firstErr: string | null = null;
    for (let i = 0; i < rows.length; i++) {
      try {
        await db.insert(table).values(prepRow(table, rows[i], {}, i)).returning();
        applied++;
      } catch (e: any) {
        if (firstErr === null) firstErr = String(e?.message || e).slice(0, 500);
      }
    }
    try {
      await db.execute(sql`
        INSERT INTO _forge_import_log (id, table_name, rows_applied)
        VALUES (${importId}, ${String(payload.table)}, ${applied})
        ON CONFLICT (id) DO NOTHING
      `);
    } catch (e) {
      console.warn(`[import] ${importId}: applied ${applied} rows but could not record it:`, e);
    }
    if (applied === rows.length) {
      console.log(`✅ [import] ${applied} row(s) into ${payload.table} (${importId})`);
    } else {
      console.error(`❌ [import] ${importId}: ${applied}/${rows.length} rows into ` +
                    `${payload.table}${firstErr ? ` — first error: ${firstErr}` : ""}`);
    }
  }
  return owned;
}


async function seedDomain(adminId: string | null, imported: Set<string> = new Set()): Promise<void> {
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
    // A TABLE THE OWNER LOADED IS THEIRS. The demo rows exist so an empty
    // screen is not mistaken for a broken one; a table holding the business's
    // real records does not have that problem, and the "already has rows"
    // check below does not cover it — a table with an `email` column takes
    // the email-keyed branch and would add "Customer 1" beside four hundred
    // real customers. The projection also stops emitting demo rows for an
    // imported entity; this is the same guarantee where the insert happens.
    if (imported.has(norm(t.name))) {
      console.log(`ℹ️  ${t.name} holds imported data — no demo rows`);
      return null;
    }
    try {
      const [{ c }] = await db.select({ c: sql<number>`count(*)::int` }).from(table);
      if (c > 0) {
        // Already populated — load its ids so child tables can still resolve
        // FK refs to it on a re-run (otherwise ref:parent[i] can't resolve).
        let existingIds: string[] = [];
        try {
          const existing: any[] = await db.select({ id: table.id }).from(table);
          existingIds = existing.map((r) => String(r.id));
          ids[norm(t.name)] = existingIds;
        } catch {
          /* table has no simple id column — leave pool empty */
        }
        // A table keyed by email (users) is occupied by the admin backstop
        // before the declared logins ever land, so "has rows" is not "is
        // seeded". Rows that carry an email join the table beside whatever is
        // there; the email conflict target keeps a re-run idempotent.
        const emailCol: any = (table as any).email;
        const planned: Record<string, unknown>[] =
          ((t.seed_data as Record<string, unknown>[] | undefined) ||
            (bag[t.name] as Record<string, unknown>[] | undefined) || []);
        const keyed = emailCol ? planned.filter((r) => typeof r.email === "string" && r.email) : [];
        if (keyed.length) {
          const got: string[] = [];
          for (let i = 0; i < keyed.length; i++) {
            try {
              const values = prepRow(table, keyed[i], ids, i);
              const res: any = await db.insert(table).values(values)
                .onConflictDoNothing({ target: emailCol }).returning();
              const id = res?.[0]?.id;
              if (id != null) got.push(String(id));
            } catch (e: any) {
              console.warn(`[seed] ${t.name} row ${i} (${String(keyed[i].email)}):`, String(e?.message || e).slice(0, 200));
            }
          }
          ids[norm(t.name)] = [...existingIds, ...got];
          console.log(`✅ ${t.name} already had ${c} rows — added ${got.length}/${keyed.length} keyed by email`);
          // NOTHING NEW IS NOT NOTHING. 0 here means every planned row was
          // already in the table; 0 from the insert path below means every
          // row was REFUSED. Returning the same number for both made a
          // restart report "❌ SEED MISMATCH: members planned rows inserted
          // 0" and withhold the fingerprint, so every start seeded again.
          return got.length || null;
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
        SEED_MISMATCHES += 1;
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
  const forceSeed = /^(1|true|yes)$/i.test(String(process.env.FORCE_SEED || ""));

  // THE ADMIN MUST ALWAYS EXIST — the skip gates below preserve DOMAIN data,
  // never the sign-in. Skipping the whole seed when FORGE_KEEP_DB_STATE=1 left
  // a DB with a schema and no users: a database reused from an earlier deploy
  // attempt was never seeded, so `admin@example.com` never existed and login
  // was impossible. `seedAdmin` upserts on email, so running it every time is
  // idempotent and never clobbers a real admin.
  const adminId = await seedAdmin();
  await ensureAccountRow(adminId, ADMIN_EMAIL, "Admin");

  // AND SO MUST THE PEOPLE THE OWNER ADDED — for the same reason and above the
  // same gates. An app whose staff cannot log in is not in use.
  await seedAccounts();

  // THE OWNER'S OWN RECORDS COME BEFORE THE DEMO ONES, and before both skip
  // gates below: a database reused from an earlier deploy must still take the
  // spreadsheet they loaded, and once their rows are in, the demo pass sees a
  // populated table and leaves it alone. After the accounts, because a row
  // that FKs a person wants that person to exist.
  const importedTables = await applyImports();

  // Idempotency gate — preserve existing DOMAIN data when the DB is being
  // reused (redeploy) or the schema shape is unchanged and data is present.
  // Override with FORCE_SEED=1 for a manual reseed (after a data wipe or when
  // developing seed content). The admin is already ensured above either way.
  if (process.env.FORGE_KEEP_DB_STATE === "1" && !forceSeed) {
    console.log("[seed] FORGE_KEEP_DB_STATE=1 — admin ensured; preserving domain data");
    return;
  }
  const currentFp = computeSchemaFingerprint();
  if (!forceSeed && await shouldSkipSeed(currentFp)) {
    console.log(
      `[seed] shape unchanged (fingerprint=${currentFp}) + data present — ` +
      `admin ensured, skipping domain data. Set FORCE_SEED=1 to reseed.`
    );
    return;
  }
  await seedDomain(adminId, importedTables);
  // A SEED THAT FAILED IS NOT A SEED TO SKIP NEXT TIME. The fingerprint was
  // recorded after every table had refused its rows (0l133sp2: no tables yet),
  // and each later start saw "shape unchanged + data present" — the admin's
  // own account row — and never seeded the demo data at all.
  if (SEED_MISMATCHES > 0) {
    console.warn(`[seed] ${SEED_MISMATCHES} table(s) took no rows — fingerprint NOT recorded, the next start seeds again.`);
    return;
  }
  await recordSeedFingerprint(currentFp);
  console.log(`[seed] complete — fingerprint recorded (${currentFp}).`);
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("Seed failed:", err);
    process.exit(1);
  });
