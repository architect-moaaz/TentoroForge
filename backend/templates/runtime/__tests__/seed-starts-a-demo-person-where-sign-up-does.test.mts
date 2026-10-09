/**
 * A demo person starts where a new person does.
 *
 * ToroCommerce's demo customer was seeded with status "Default Customer
 * (demo)" — the placeholder every unknown text column got — where sign-up
 * writes "active". Its guard read that as a disabled account, and every
 * customer process the build tried was refused (2026-10-09). The seed now
 * starts a demo person's row from `ACCOUNT_INITIAL`, the values sign-up uses,
 * and puts right a row an earlier seed filled with its own placeholder.
 *
 * Runs the SHIPPED seed.ts with the database stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "seed-demo-account-"));
mkdirSync(join(dir, "src", "db"), { recursive: true });
process.chdir(dir);

const col = (columnType: string, dataType: string) => ({ columnType, dataType });
const tables: Record<string, any> = {
  customers: {
    __name: "customers",
    id: { columnType: "PgUUID", dataType: "string", notNull: true },
    email: { columnType: "PgText", dataType: "string", notNull: true },
    fullName: { columnType: "PgText", dataType: "string", notNull: true },
    status: { columnType: "PgText", dataType: "string", notNull: true },
  },
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
  // An earlier seed made the Finance demo login and filled its account row
  // with its own placeholder; the Customer demo login is new.
  users: [{ id: "u-fin", email: "finance@example.com", password: "x", name: "Finance (demo)",
            accountType: "Finance", isActive: true }],
  customers: [{ id: "u-fin", email: "finance@example.com", fullName: "Finance (demo)",
                status: "Default Finance (demo)" }],
  forge_invites: [],
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
        // With no target (the account row) the conflict is on its id.
        onConflictDoNothing: (opts: any = {}) => {
          const hit = opts.target ? conflicting(opts.target) : (rows[name] ?? []).find((r) => r.id === v.id);
          const result = hit ? [] : insert();
          return Object.assign(Promise.resolve(result), { returning: async () => result });
        },
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
    "../lib/account":
      "export const ACCOUNT = { entity: 'Customer', fields: [{ name: 'fullName', kind: 'text', required: true }," +
      " { name: 'email', kind: 'email', required: true }], labelField: 'fullName', locationField: null };" +
      "export const ACCOUNT_INITIAL = { status: 'active' };" +
      "export const ADMIN_ROLE = 'Admin'; export const SIGNUP_ROLE = 'Customer'; export const ROLES = ['Admin', 'Customer', 'Finance'];",
    "../lib/account-table": "export const accountTable = globalThis.__tables.customers;",
    "./index": "export const db = globalThis.__db;",
    "./schema": "export const users = globalThis.__tables.users; export const forgeInvites = globalThis.__tables.forgeInvites;" +
      " export const customers = globalThis.__tables.customers;",
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

const realExit = process.exit;
(process as any).exit = (code?: number) => { (globalThis as any).__seedExit = code; };
await import("../seed.ts");
for (let i = 0; i < 50 && (globalThis as any).__seedExit === undefined; i++) {
  await new Promise((r) => setTimeout(r, 100));
}
(process as any).exit = realExit;

const login = (rows.users ?? []).find((r) => r.email === "customer@example.com");
ok(!!login, "the Customer role has a demo login");
const account = (rows.customers ?? []).find((r) => r.id === login?.id);
ok(!!account, "and the account row sign-up would give it");
eqJson(account?.status, "active", "starting where a new account starts, not as 'Default Customer (demo)'");
eqJson(account?.fullName, "Customer (demo)", "under the demo person's name");

const finance = (rows.customers ?? []).find((r) => r.id === "u-fin");
eqJson(finance?.status, "active", "a row an earlier seed left as a placeholder is put right");

const admin = (rows.users ?? []).find((r) => r.email === "admin@example.com");
const adminRow = (rows.customers ?? []).find((r) => r.id === admin?.id);
ok(!adminRow || adminRow.status !== "Default Admin", "the administrator's row is not a placeholder either");

done();
