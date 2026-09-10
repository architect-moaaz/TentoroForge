/**
 * DEFECT (QA E-04, "seeded data appears"): the projection writes label
 * placeholders for values it can't derive — "Start Time 1" for a timestamp
 * column, "Owner Id 1" for a uuid FK. The seed then CRASHED the whole table:
 * a date-mode column made drizzle call `.toISOString()` on the string
 * ("value.toISOString is not a function"), and a NOT NULL uuid FK whose stem
 * didn't literally name a seeded pool (`ownerId`, `petOwnerId`,
 * `productCategoryId`) stayed null and failed the insert. Every domain table
 * shipped empty.
 *
 * The seed now (a) coerces a value a date/timestamp column can't accept to a
 * valid Date / calendar string, and (b) resolves an FK by user-semantic suffix
 * (`ownerId`/`petOwnerId` → users) and by singularized table suffix
 * (`productCategoryId` → categories). Runs the SHIPPED seed.ts, DB stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "seed2-"));
mkdirSync(join(dir, "src", "db"), { recursive: true });
writeFileSync(join(dir, "src", "db", "seed.json"), JSON.stringify({
  // All values are the projection's label placeholders — nothing here is a
  // real date or a real uuid; the seed must make each row insertable anyway.
  categories: [{ name: "Category 1" }],
  pets: [{ name: "Pet 1", ownerId: "Owner Id 1", dob: "Date Of Birth 1" }],
  products: [{ name: "Product 1", productCategoryId: "Product Category Id 1",
              releaseDate: "Release Date 1" }],
}));
process.chdir(dir);

const inserted: Record<string, any[]> = {};
const col = (columnType: string, dataType: string, notNull = false) => ({ columnType, dataType, notNull });
const tables: Record<string, any> = {
  users: { __name: "users", id: col("PgUUID", "string"), email: col("PgText", "string"), passwordHash: col("PgText", "string"), name: col("PgText", "string"), role: col("PgText", "string") },
  categories: { __name: "categories", id: col("PgUUID", "string"), name: col("PgText", "string") },
  pets: { __name: "pets", id: col("PgUUID", "string"), name: col("PgText", "string"), ownerId: col("PgUUID", "string", true), dob: col("PgTimestamp", "date", true) },
  products: { __name: "products", id: col("PgUUID", "string"), name: col("PgText", "string"), productCategoryId: col("PgUUID", "string", true), releaseDate: col("PgTimestamp", "date", true) },
};
let counter = 0;
const db = {
  insert: (table: any) => ({ values: (v: any) => ({
    returning: async () => {
      const name = table.__name;
      // Enforce the NOT NULL FK/date constraints the real DB would, so the
      // test fails loudly if resolution/coercion regresses.
      for (const [k, c] of Object.entries(table) as any) {
        if (k === "__name") continue;
        if (c.notNull && (v[k] === null || v[k] === undefined))
          throw new Error(`null value in column "${k}" violates not-null constraint`);
        if (c.dataType === "date" && v[k] != null && !(v[k] instanceof Date))
          throw new Error(`value.toISOString is not a function`);
      }
      const row = { id: `id-${++counter}`, ...v };
      (inserted[name] ??= []).push(row);
      return [row];
    },
    onConflictDoUpdate: () => ({ returning: async () => [{ id: "admin" }] }),
    onConflictDoNothing: () => ({ returning: async () => [{ id: "admin" }] }),
  }) }),
  select: (shape?: any) => ({ from: (table: any) => {
    const name = table.__name;
    const rows = inserted[name] ?? [];
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
    "./schema": "export const users = globalThis.__tables.users; export const categories = globalThis.__tables.categories; export const pets = globalThis.__tables.pets; export const products = globalThis.__tables.products;",
    "bcryptjs": "export default { hashSync: () => 'hash', hash: async () => 'hash' };",
    "drizzle-orm": "export const sql = (s) => ({ s }); sql.raw = (s) => ({ s }); export const eq = () => ({}); export const getTableColumns = (t) => Object.fromEntries(Object.entries(t).filter(([k]) => k !== '__name'));",
  },
});
(globalThis as any).__db = db;
(globalThis as any).__tables = tables;

const realExit = process.exit;
(process as any).exit = (code?: number) => { (globalThis as any).__seedExit = code; };
await import("../seed.ts");
for (let i = 0; i < 50 && (globalThis as any).__seedExit === undefined; i++) await new Promise((r) => setTimeout(r, 100));
(process as any).exit = realExit;

// seedAdmin pins the admin id and inserts via onConflictDoNothing, which the
// stub answers with { id: "admin" }; seedDomain pre-loads ids["users"] with it.
ok((inserted.pets ?? []).length === 1, "pets seeded despite a label ownerId and a label date");
ok(inserted.pets?.[0]?.dob instanceof Date, "a garbage date string became a Date, not a crash");
eqJson(inserted.pets?.[0]?.ownerId, "admin", "ownerId resolved to the seeded users pool (user-semantic)");
ok((inserted.products ?? []).length === 1, "products seeded — a compound FK resolved");
eqJson(inserted.products?.[0]?.productCategoryId, inserted.categories?.[0]?.id,
  "productCategoryId resolved to the categories pool by singularized suffix");
ok(inserted.products?.[0]?.releaseDate instanceof Date, "products.releaseDate coerced to a Date");
done("seed-semantic-fk");
