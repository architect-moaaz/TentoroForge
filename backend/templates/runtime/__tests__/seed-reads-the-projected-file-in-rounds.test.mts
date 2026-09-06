/**
 * The runtime seed read only the legacy plan file, so a Blueprint-built app
 * seeded nothing but the admin. It now reads the projection's
 * src/db/seed.json, seeds tables in rounds so a child is retried after its
 * parent, resolves `ref:<table>[i]` to the parent's inserted id, and binds
 * an ISO string as a Date only where drizzle's dataType is "date". Runs the
 * SHIPPED seed.ts with the database stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "seed-"));
mkdirSync(join(dir, "src", "db"), { recursive: true });
writeFileSync(join(dir, "src", "db", "seed.json"), JSON.stringify({
  // alphabetical, child first: the rounds must seed the parent first
  bill_sponsors: [{ billId: "ref:bills[0]", role: "LEAD" }],
  bills: [{ title: "Bill 1", introducedOn: "2026-02-15T09:00:00Z", createdAt: "2026-02-15T09:00:00Z" }],
}));
process.chdir(dir);

const inserted: Record<string, any[]> = {};
const col = (columnType: string, dataType: string) => ({ columnType, dataType });
const tables: Record<string, any> = {
  users: { __name: "users", id: col("PgUUID", "string"), email: col("PgText", "string"), passwordHash: col("PgText", "string"), name: col("PgText", "string"), role: col("PgText", "string") },
  bills: { __name: "bills", id: col("PgUUID", "string"), title: col("PgText", "string"), introducedOn: col("PgDateString", "string"), createdAt: col("PgTimestamp", "date") },
  billSponsors: { __name: "bill_sponsors", id: col("PgUUID", "string"), billId: col("PgUUID", "string"), role: col("PgText", "string") },
};
let counter = 0;
const db = {
  insert: (table: any) => ({ values: (v: any) => ({
    returning: async () => {
      const name = table.__name;
      if (name === "bill_sponsors" && !v.billId) throw new Error('null value in column "bill_id"');
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
    "./schema": "export const users = globalThis.__tables.users; export const bills = globalThis.__tables.bills; export const billSponsors = globalThis.__tables.billSponsors;",
    "bcryptjs": "export default { hashSync: () => 'hash', hash: async () => 'hash' };",
    "drizzle-orm": "export const sql = (s) => ({ s }); sql.raw = (s) => ({ s }); export const eq = () => ({}); export const getTableColumns = (t) => Object.fromEntries(Object.entries(t).filter(([k]) => k !== '__name'));",
  },
});
(globalThis as any).__db = db;
(globalThis as any).__tables = tables;

// The script ends with process.exit; the assertions below must still run.
const realExit = process.exit;
(process as any).exit = (code?: number) => { (globalThis as any).__seedExit = code; };
await import("../seed.ts");
for (let i = 0; i < 50 && (globalThis as any).__seedExit === undefined; i++) await new Promise((r) => setTimeout(r, 100));
(process as any).exit = realExit;

ok((inserted.bills ?? []).length === 1, "the parent table seeded from the projection's file");
ok((inserted.bill_sponsors ?? []).length === 1, "the child seeded in a later round, after its parent");
eqJson(inserted.bill_sponsors?.[0]?.billId, inserted.bills?.[0]?.id, "ref:bills[0] resolved to the parent's id");
eqJson(inserted.bills?.[0]?.introducedOn, "2026-02-15", "a string-mode date column receives a calendar date");
ok(inserted.bills?.[0]?.createdAt instanceof Date, "a timestamp column receives a Date");
done("seed");
