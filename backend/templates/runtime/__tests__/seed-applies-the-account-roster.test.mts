/**
 * The seed applies the owner's roster of people who log in.
 *
 * An account has to survive a redeploy or it is not an account, so who may log
 * in is a file in the project (`src/db/accounts.json`, written by Smith from
 * `.forge/accounts.json`) that the seed applies on every start — beside the
 * admin, above the skip gates that preserve domain data.
 *
 * Three things have to hold, and each was a way to lock someone out:
 *   1. a new account is created with a password nobody holds and inactive, and
 *      its one-time setup link is opened;
 *   2. an invite the seed has ALREADY applied is left alone — otherwise every
 *      restart re-opened a spent link and cleared a password the person had
 *      chosen;
 *   3. a removed person is deactivated and their pending link spent, because
 *      setting a password activates an account and would let them back in.
 *
 * Runs the SHIPPED seed.ts with the database stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "seed-accounts-"));
mkdirSync(join(dir, "src", "db"), { recursive: true });
const soon = new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString();
writeFileSync(join(dir, "src", "db", "accounts.json"), JSON.stringify({
  accounts: [
    { email: "dave@clinic.com", name: "Dave Okafor", role: "Ward Manager", status: "active",
      invite: { issue: "INV-new", tokenHash: "hash-for-dave", purpose: "invite", expiresAt: soon } },
    // Already applied: the row below is in forge_invites before the seed runs.
    { email: "mo@clinic.com", name: "Mo", status: "active",
      invite: { issue: "INV-old", tokenHash: "hash-for-mo", purpose: "invite", expiresAt: soon } },
    { email: "sarah@clinic.com", name: "Sarah", status: "removed", invite: null },
  ],
}));
process.chdir(dir);

const col = (columnType: string, dataType: string) => ({ columnType, dataType });
const tables: Record<string, any> = {
  users: {
    __name: "users",
    id: col("PgUUID", "string"), email: col("PgText", "string"),
    password: col("PgText", "string"), name: col("PgText", "string"),
    accountType: col("PgText", "string"), isActive: col("PgBoolean", "boolean"),
  },
  forgeInvites: {
    __name: "forge_invites",
    id: col("PgUUID", "string"), email: col("PgText", "string"),
    tokenHash: col("PgText", "string"), issue: col("PgText", "string"),
    purpose: col("PgText", "string"), expiresAt: col("PgTimestamp", "date"),
    usedAt: col("PgTimestamp", "date"), createdAt: col("PgTimestamp", "date"),
  },
};
// `eq` carries which column it compares so the stub can filter like a database.
const columnName = (table: any, colRef: any): string =>
  Object.keys(table).find((k) => table[k] === colRef) ?? "";

const rows: Record<string, any[]> = {
  // Mo chose a password last week; Sarah is a live account being retired.
  users: [
    { id: "u-mo", email: "mo@clinic.com", password: "chosen-by-mo", name: "Mo", isActive: true },
    { id: "u-sarah", email: "sarah@clinic.com", password: "chosen-by-sarah", name: "Sarah", isActive: true },
  ],
  forge_invites: [
    { id: "i-old", email: "mo@clinic.com", tokenHash: "hash-for-mo", issue: "INV-old",
      purpose: "invite", expiresAt: new Date(soon), usedAt: new Date("2026-09-01") },
    { id: "i-sarah", email: "sarah@clinic.com", tokenHash: "hash-for-sarah", issue: "INV-sarah",
      purpose: "invite", expiresAt: new Date(soon), usedAt: null },
  ],
};

let counter = 0;
const matches = (row: any, cond: any) =>
  !cond || cond.column === undefined || row[cond.column] === cond.value;

const db = {
  insert: (table: any) => ({
    values: (v: any) => {
      const name = table.__name;
      const insert = (): any[] => {
        const row = { id: `id-${++counter}`, ...v };
        (rows[name] ??= []).push(row);
        return [row];
      };
      const conflicting = (target: any): any | undefined => {
        const key = columnName(table, target);
        return (rows[name] ?? []).find((r) => key && r[key] === v[key]);
      };
      const chain: any = {
        returning: async () => insert(),
        onConflictDoNothing: ({ target }: any) => ({
          returning: async () => (conflicting(target) ? [] : insert()),
        }),
        onConflictDoUpdate: ({ target, set }: any) => {
          const hit = conflicting(target);
          if (hit) Object.assign(hit, set);
          else insert();
          return Promise.resolve([]);
        },
      };
      return chain;
    },
  }),
  update: (table: any) => ({
    set: (v: any) => ({
      where: async (cond: any) => {
        for (const row of rows[table.__name] ?? []) {
          if (matches(row, cond)) Object.assign(row, v);
        }
        return [];
      },
    }),
  }),
  select: (shape?: any) => ({
    from: (table: any) => {
      let cond: any = null;
      const all = () => (rows[table.__name] ?? []).filter((r) => matches(r, cond));
      const q: any = {
        where: (c: any) => { cond = c; return q; },
        limit: () => q,
        then: (res: any, rej: any) =>
          Promise.resolve(shape && "c" in shape ? [{ c: all().length }] : all()).then(res, rej),
      };
      return q;
    },
  }),
  execute: async () => [],
};

installHarness({
  stubs: {
    "./index": "export const db = globalThis.__db;",
    "./schema": "export const users = globalThis.__tables.users; export const forgeInvites = globalThis.__tables.forgeInvites;",
    // A distinct hash per call, the way bcrypt gives one: the point of the
    // random-UUID password is that two accounts never share a hash.
    "bcryptjs": "let n = 0; export default { hashSync: () => 'hash', hash: async (s) => `bcrypt(${s})#${++n}` };",
    "drizzle-orm":
      "export const sql = (s) => ({ s }); sql.raw = (s) => ({ s });" +
      "export const eq = (col, value) => ({ column: globalThis.__columnOf(col), value });" +
      "export const getTableColumns = (t) => Object.fromEntries(Object.entries(t).filter(([k]) => k !== '__name'));",
  },
});
(globalThis as any).__db = db;
(globalThis as any).__tables = tables;
(globalThis as any).__columnOf = (colRef: any) => {
  for (const table of Object.values(tables)) {
    const key = columnName(table, colRef);
    if (key) return key;
  }
  return undefined;
};

// The script ends with process.exit; the assertions below must still run.
const realExit = process.exit;
(process as any).exit = (code?: number) => { (globalThis as any).__seedExit = code; };
await import("../seed.ts");
for (let i = 0; i < 50 && (globalThis as any).__seedExit === undefined; i++) {
  await new Promise((r) => setTimeout(r, 100));
}
(process as any).exit = realExit;

const user = (email: string) => (rows.users ?? []).find((r) => r.email === email);
const invite = (email: string) => (rows.forge_invites ?? []).filter((r) => r.email === email);

// 1. A NEW ACCOUNT.
const dave = user("dave@clinic.com");
ok(!!dave, "the person the owner added has an account");
ok(!!dave && /^bcrypt\(/.test(String(dave.password)), "created with a bcrypt hash, not a password");
ok(!!dave && !String(dave.password).includes("hash-for-dave"),
   "and not with the invite's token, which is not a credential");
eqJson(dave?.isActive, false, "inactive until its person sets the password");
eqJson(dave?.name, "Dave Okafor", "under the name they were added with");
eqJson(dave?.accountType, "Ward Manager",
       "signing in as the role they were added for (no role column: accountType)");
const daveInvite = invite("dave@clinic.com");
eqJson(daveInvite.length, 1, "with one setup link");
eqJson(daveInvite[0]?.issue, "INV-new", "the issuance the roster named");
eqJson(daveInvite[0]?.usedAt, null, "unspent");

// 2. AN INVITE ALREADY APPLIED IS LEFT ALONE.
eqJson(user("mo@clinic.com")?.password, "chosen-by-mo",
       "a password already chosen survives a restart");
eqJson(user("mo@clinic.com")?.isActive, true, "and so does the account being usable");
eqJson(invite("mo@clinic.com").length, 1, "the spent link is not reissued");
ok(invite("mo@clinic.com")[0]?.usedAt !== null, "and stays spent");

// 3. A REMOVED PERSON.
eqJson(user("sarah@clinic.com")?.isActive, false, "a removed person cannot sign in");
ok(!!user("sarah@clinic.com"), "but their row stays — their records point at it");
ok(invite("sarah@clinic.com")[0]?.usedAt instanceof Date,
   "and their pending link is spent, since setting a password would readmit them");

// The admin is untouched by any of this.
ok(!!user("admin@example.com"), "the seeded administrator is still created");

done("seed account roster");
