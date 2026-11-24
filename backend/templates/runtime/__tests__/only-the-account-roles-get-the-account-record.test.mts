/**
 * Only the roles whose login IS a row of the account entity get that row.
 *
 * DITANS's account entity is the Candidate. The seed gave every seeded login a
 * Candidate record — the administrator, each member of staff, the recruiter —
 * and so did each employer's signup (2026-11-24). `security.accountRoles`
 * says whose record it is; the projector writes it as ACCOUNT_ROLES.
 *
 * Runs the SHIPPED seed.ts with the database stubbed, twice: with the list
 * declared (ACCOUNT_ROLES_DECLARED=1) and without it, when every login has one
 * as before.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const declared = process.env.ACCOUNT_ROLES_DECLARED === "1";
const dir = mkdtempSync(join(tmpdir(), "seed-account-roles-"));
mkdirSync(join(dir, "src", "db"), { recursive: true });
writeFileSync(join(dir, "src", "db", "accounts.json"), JSON.stringify({
  accounts: [
    { email: "ops@ditans.example", name: "Ops Person", role: "Operations", status: "active", invite: null },
    { email: "nurse@example.com", name: "A Nurse", role: "Candidate", status: "active", invite: null },
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
  candidates: {
    __name: "candidates",
    id: col("PgUUID", "string"), email: col("PgText", "string"), fullName: col("PgText", "string"),
  },
};
const columnName = (table: any, colRef: any): string =>
  Object.keys(table).find((k) => table[k] === colRef) ?? "";
const rows: Record<string, any[]> = { users: [], forge_invites: [], candidates: [] };
let counter = 0;
const matches = (row: any, cond: any) => !cond || cond.column === undefined || row[cond.column] === cond.value;
const db = {
  insert: (table: any) => ({
    values: (v: any) => {
      const name = table.__name;
      const insert = (): any[] => { const row = { id: `id-${++counter}`, ...v }; (rows[name] ??= []).push(row); return [row]; };
      const conflicting = (target: any): any | undefined => {
        const key = target ? columnName(table, target) : "id";
        return (rows[name] ?? []).find((r) => key && r[key] === v[key]);
      };
      const chain: any = {
        returning: async () => insert(),
        onConflictDoNothing: (o?: any) => {
          const p: any = Promise.resolve().then(() => (conflicting(o?.target) ? [] : insert()));
          p.returning = async () => p;
          return p;
        },
        onConflictDoUpdate: ({ target, set }: any) => {
          const hit = conflicting(target); if (hit) Object.assign(hit, set); else insert(); return Promise.resolve([]);
        },
        then: (res: any, rej: any) => Promise.resolve(insert()).then(res, rej),
      };
      return chain;
    },
  }),
  update: (table: any) => ({
    set: (v: any) => ({ where: async (cond: any) => { for (const r of rows[table.__name] ?? []) if (matches(r, cond)) Object.assign(r, v); return []; } }),
  }),
  select: (shape?: any) => ({
    from: (table: any) => {
      let cond: any = null;
      const all = () => (rows[table.__name] ?? []).filter((r) => matches(r, cond));
      const q: any = {
        where: (c: any) => { cond = c; return q; }, limit: () => q,
        then: (res: any, rej: any) => Promise.resolve(shape && "c" in shape ? [{ c: all().length }] : all()).then(res, rej),
      };
      return q;
    },
  }),
  execute: async () => [],
};

const account = JSON.stringify({ entity: "Candidate", fields: [
  { name: "fullName", label: "Full name", kind: "text", required: true },
  { name: "email", label: "Email", kind: "email", required: true }], labelField: "fullName", locationField: null });
installHarness({
  stubs: {
    "../lib/account":
      `export const ACCOUNT = ${account}; export const ADMIN_ROLE = 'Organisation Admin'; export const SIGNUP_ROLE = 'Candidate';` +
      ` export const ROLES = ['Candidate', 'Organisation Admin', 'Recruiter', 'Operations'];` +
      (declared ? ` export const ACCOUNT_ROLES = ['Candidate'];` : ""),
    "../lib/account-table": "export const accountTable = globalThis.__tables.candidates;",
    "./index": "export const db = globalThis.__db;",
    "./schema": "export const users = globalThis.__tables.users; export const forgeInvites = globalThis.__tables.forgeInvites;",
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
  for (const table of Object.values(tables)) { const key = columnName(table, colRef); if (key) return key; }
  return undefined;
};

const realExit = process.exit;
(process as any).exit = (code?: number) => { (globalThis as any).__seedExit = code; };
await import("../seed.ts");
for (let i = 0; i < 50 && (globalThis as any).__seedExit === undefined; i++) await new Promise((r) => setTimeout(r, 100));
(process as any).exit = realExit;

const loginId = (email: string) => rows.users.find((r) => r.email === email)?.id;
const hasRecord = (email: string) => { const id = loginId(email); return !!id && rows.candidates.some((c) => c.id === id); };

ok(!!loginId("candidate@example.com") && !!loginId("recruiter@example.com") && !!loginId("admin@example.com"),
   "every role still gets its demo login");
ok(hasRecord("candidate@example.com"), "the candidate's login is a Candidate record");
ok(hasRecord("nurse@example.com"), "and so is a rostered candidate's");
if (declared) {
  eqJson(hasRecord("recruiter@example.com"), false, "a recruiter signs in with a login alone");
  eqJson(hasRecord("operations@example.com"), false, "so does a member of staff");
  eqJson(hasRecord("admin@example.com"), false, "and the administrator");
  eqJson(hasRecord("ops@ditans.example"), false, "and a rostered member of staff");
  eqJson(rows.candidates.length, 2, "two Candidate records: the two candidates");
} else {
  ok(hasRecord("recruiter@example.com") && hasRecord("admin@example.com") && hasRecord("ops@ditans.example"),
     "undeclared, every login has one, as before");
}
done("only the account roles get the account record");
