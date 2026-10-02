/**
 * A seeded row's password column, whatever the plan put in it.
 *
 * The plan's value is either a plaintext ("Passw0rd!") or a label ("Password
 * Hash 1"), and it was inserted verbatim. Two different things broke:
 *
 *   1. `auth.ts` bcrypt-compares what it finds, so every seeded account
 *      existed and NOBODY COULD SIGN INTO IT — while a plaintext password sat
 *      in the database and in the committed seed file (§42);
 *   2. a plan naming the column `passwordHash` matched no column on the
 *      shipped table (the platform calls it `password`), so the key was
 *      dropped, the NOT NULL insert failed, and the whole staff list seeded
 *      nothing.
 *
 * Now the column is filled with the bcrypt hash of a fresh random UUID: the
 * row exists as data, and the account cannot be signed into — the honest state
 * of an account nobody was given. `admin@example.com` and the invited accounts
 * are the ways in, and neither comes through this path.
 *
 * Runs the SHIPPED seed.ts with the database stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "seed-credential-"));
mkdirSync(join(dir, "src", "db"), { recursive: true });
writeFileSync(join(dir, "src", "db", "seed.json"), JSON.stringify({
  // Three shapes the two producers actually emit, in one file.
  staff: [
    { email: "nurse1@example.com", name: "Nurse 1", password: "Passw0rd!" },
    { email: "nurse2@example.com", name: "Nurse 2", passwordHash: "Password Hash 2" },
  ],
  // An ordinary table, to prove the rule reaches no further than it says.
  recipes: [{ title: "Focaccia", salt: "10g", passes: 3 }],
}));
process.chdir(dir);

const inserted: Record<string, any[]> = {};
const col = (columnType: string, dataType: string, notNull = false) =>
  ({ columnType, dataType, notNull });
const tables: Record<string, any> = {
  // No `users` table on purpose: `staff` is what this app authenticates
  // against, and the rule is about the column, not the table's name.
  staff: {
    __name: "staff",
    id: col("PgUUID", "string"), email: col("PgText", "string"),
    name: col("PgText", "string"), password: col("PgText", "string", true),
  },
  recipes: {
    __name: "recipes",
    id: col("PgUUID", "string"), title: col("PgText", "string"),
    salt: col("PgText", "string"), passes: col("PgInteger", "number"),
  },
};

let counter = 0;
const db = {
  insert: (table: any) => ({ values: (v: any) => ({
    returning: async () => {
      const name = table.__name;
      // The shipped table has `password`, so a row that never sets it fails
      // exactly as Postgres would — that is failure mode 2.
      if (name === "staff" && v.password == null) {
        throw new Error('null value in column "password" violates not-null constraint');
      }
      const row = { id: `id-${++counter}`, ...v };
      (inserted[name] ??= []).push(row);
      return [row];
    },
    onConflictDoUpdate: () => ({ returning: async () => [{ id: "x" }] }),
    onConflictDoNothing: () => ({ returning: async () => [{ id: "x" }] }),
  }) }),
  select: (shape?: any) => ({ from: (table: any) => {
    const rows = inserted[table.__name] ?? [];
    const q: any = Promise.resolve(shape && "c" in shape ? [{ c: rows.length }] : rows);
    q.where = () => Promise.resolve(shape && "c" in shape ? [{ c: rows.length }] : rows);
    q.limit = () => q;
    return q;
  } }),
  execute: async () => [],
};

installHarness({
  stubs: {
    "./index": "export const db = globalThis.__db;",
    "./schema": "export const staff = globalThis.__tables.staff; export const recipes = globalThis.__tables.recipes;",
    // The real algorithm's shape, distinctly marked so a test can tell a hash
    // from the plaintext that was going in before.
    "bcryptjs": "export default { hashSync: (s) => `bcrypt(${s})`, hash: async (s) => `bcrypt(${s})` };",
    "drizzle-orm": "export const sql = (s) => ({ s }); sql.raw = (s) => ({ s }); export const eq = () => ({}); export const getTableColumns = (t) => Object.fromEntries(Object.entries(t).filter(([k]) => k !== '__name'));",
  },
});
(globalThis as any).__db = db;
(globalThis as any).__tables = tables;

const realExit = process.exit;
(process as any).exit = (code?: number) => { (globalThis as any).__seedExit = code; };
await import("../seed.ts");
for (let i = 0; i < 50 && (globalThis as any).__seedExit === undefined; i++) {
  await new Promise((r) => setTimeout(r, 100));
}
(process as any).exit = realExit;

const staff = inserted.staff ?? [];

// 1. THE ROWS SEED AT ALL — including the one whose plan named the column the
//    platform does not ship.
eqJson(staff.length, 2, "both staff rows seeded");
eqJson(staff.map((r) => r.email).sort(),
       ["nurse1@example.com", "nurse2@example.com"],
       "the row naming `passwordHash` is no longer lost to a NOT NULL failure");

// 2. NO READABLE CREDENTIAL REACHED THE DATABASE.
ok(staff.every((r) => String(r.password).startsWith("bcrypt(")),
   "every seeded row's password column holds a bcrypt hash");
ok(!staff.some((r) => JSON.stringify(r).includes("Passw0rd!")),
   "the plan's plaintext password is nowhere in the row");
ok(!staff.some((r) => JSON.stringify(r).includes("Password Hash 2")),
   "and neither is its label");
ok(staff[0]?.password !== staff[1]?.password,
   "each row's hash is its own, so one account is not every account");
ok(!staff.some((r) => "passwordHash" in r),
   "nothing writes a column the shipped table does not have");

// 3. THE RULE REACHES NO FURTHER THAN IT SAYS. `salt` is a real column in a
//    recipe app and `passes` a real one in a gym; corrupting them to fix a
//    credential would trade one broken app for another.
const recipe = (inserted.recipes ?? [])[0];
eqJson(recipe?.salt, "10g", "an ordinary `salt` column keeps its value");
eqJson(recipe?.passes, 3, "and so does `passes`");

done("seed credential");
