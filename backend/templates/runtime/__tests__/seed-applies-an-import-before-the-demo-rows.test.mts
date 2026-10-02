/**
 * The owner's spreadsheet reaches their database, once.
 *
 * Every owner arrives with an existing business and existing data, and until
 * `applyImports` there was no route for it: the first real use of a generated
 * app was typing everything in again. The rows land through the seeder — the
 * only thing in the product that writes rows — and three properties have to
 * hold or the feature is worse than nothing:
 *
 *   1. they are inserted BEFORE the demo rows, so the demo pass sees a
 *      populated table and "Customer 1" never sits beside a real customer;
 *   2. an import already in `_forge_import_log` is not applied again, so a
 *      redeploy does not give them every customer twice;
 *   3. a payload naming a table the schema no longer has is reported and
 *      skipped, not crashed on.
 *
 * Runs the SHIPPED seed.ts with the database stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "seed-import-"));
mkdirSync(join(dir, "src", "db", "imports"), { recursive: true });

// What the projection writes: demo rows for the entity that has no import.
writeFileSync(join(dir, "src", "db", "seed.json"), JSON.stringify({
  customers: [{ fullName: "Customer 1", email: "customer1@example.com" }],
  suppliers: [{ name: "Supplier 1" }],
}));
// What services.smith.data_import writes: the owner's own records.
writeFileSync(join(dir, "src", "db", "imports", "IMP-aaaaaaaaaa.json"), JSON.stringify({
  import: "IMP-aaaaaaaaaa", table: "customers", source: "customers.csv",
  rows: [{ fullName: "Annika Rahman", email: "annika@rahman.co" },
         { fullName: "Boris Vale", email: "boris@vale.io" }],
}));
// One already applied on an earlier boot, and one for a table that is gone.
writeFileSync(join(dir, "src", "db", "imports", "IMP-bbbbbbbbbb.json"), JSON.stringify({
  import: "IMP-bbbbbbbbbb", table: "customers", source: "again.csv",
  rows: [{ fullName: "Should Not Land", email: "no@example.com" }],
}));
writeFileSync(join(dir, "src", "db", "imports", "IMP-cccccccccc.json"), JSON.stringify({
  import: "IMP-cccccccccc", table: "wards", source: "wards.csv",
  rows: [{ name: "Ward A" }],
}));
process.chdir(dir);

const inserted: Record<string, any[]> = {};
const logged: string[] = [];
const col = (columnType: string, dataType: string) => ({ columnType, dataType });
const tables: Record<string, any> = {
  users: { __name: "users", id: col("PgUUID", "string"), email: col("PgText", "string"), password: col("PgText", "string"), name: col("PgText", "string"), role: col("PgText", "string") },
  customers: { __name: "customers", id: col("PgUUID", "string"), fullName: col("PgText", "string"), email: col("PgText", "string") },
  suppliers: { __name: "suppliers", id: col("PgUUID", "string"), name: col("PgText", "string") },
};
let counter = 0;
const db = {
  // EVERY insert is recorded, including the conflict-guarded ones. An earlier
  // version of this stub dropped `onConflictDoNothing` inserts on the floor,
  // and the assertion that no demo row lands beside the real ones passed
  // while the seed was in fact adding one.
  insert: (table: any) => {
    const land = (v: any) => {
      const row = { id: `id-${++counter}`, ...v };
      (inserted[table.__name] ??= []).push(row);
      return [row];
    };
    return { values: (v: any) => ({
      returning: async () => land(v),
      onConflictDoUpdate: () => ({ returning: async () => land(v) }),
      onConflictDoNothing: () => ({ returning: async () => land(v) }),
    }) };
  },
  select: (shape?: any) => ({ from: (table: any) => {
    const rows = inserted[table.__name] ?? [];
    const q: any = Promise.resolve(shape && "c" in shape ? [{ c: rows.length }] : rows);
    q.where = () => Promise.resolve(shape && "c" in shape ? [{ c: rows.length }] : rows);
    q.limit = () => q;
    return q;
  } }),
  // The import log, for real: a SELECT answers from what an INSERT recorded,
  // which is what makes the second run of the same import a no-op.
  execute: async (q: any) => {
    const text = String((q?.s ?? []).join?.("?") ?? q?.s ?? "");
    const values: any[] = q?.v ?? [];
    if (/SELECT rows_applied FROM _forge_import_log/i.test(text)) {
      const id = String(values[0] ?? "");
      return logged.includes(id) ? { rows: [{ rows_applied: 1 }] } : { rows: [] };
    }
    if (/INSERT INTO _forge_import_log/i.test(text)) {
      logged.push(String(values[0] ?? ""));
      return { rows: [] };
    }
    return { rows: [] };
  },
};
installHarness({
  stubs: {
    "./index": "export const db = globalThis.__db;",
    "./schema": "export const users = globalThis.__tables.users; export const customers = globalThis.__tables.customers; export const suppliers = globalThis.__tables.suppliers;",
    "bcryptjs": "export default { hashSync: () => 'hash', hash: async () => 'hash' };",
    "drizzle-orm": "export const sql = (s, ...v) => ({ s, v }); sql.raw = (s) => ({ s, v: [] }); export const eq = () => ({}); export const getTableColumns = (t) => Object.fromEntries(Object.entries(t).filter(([k]) => k !== '__name'));",
  },
});
(globalThis as any).__db = db;
(globalThis as any).__tables = tables;
// Already applied before this boot — the second file must not land again.
logged.push("IMP-bbbbbbbbbb");

const realExit = process.exit;
(process as any).exit = (code?: number) => { (globalThis as any).__seedExit = code; };
await import("../seed.ts");
for (let i = 0; i < 50 && (globalThis as any).__seedExit === undefined; i++) await new Promise((r) => setTimeout(r, 100));
(process as any).exit = realExit;

const customers = (inserted.customers ?? []).map((r) => r.fullName);
eqJson(customers, ["Annika Rahman", "Boris Vale"],
       "the owner's rows landed, and the demo row for that table never did");
ok(!customers.includes("Should Not Land"),
   "an import already in the log is not applied a second time");
ok(logged.includes("IMP-aaaaaaaaaa"), "the applied import was recorded");
eqJson((inserted.suppliers ?? []).map((r) => r.name), ["Supplier 1"],
       "a table nobody imported into still gets its demo row");
ok(!("wards" in inserted), "a payload for a table the schema does not have is skipped");
done("seed-import");
