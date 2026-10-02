/**
 * The CSV export answers who may read the data, and never carries a credential.
 *
 * This endpoint shipped in every generated app and answered ANYBODY: no
 * session, no role check, `db.select()` — so `/api/export/users` handed out
 * the password hash of every account to whoever knew the URL. The app already
 * projects the two files that answer the question (`entity-access.ts`,
 * `sensitive-columns.ts`) and the route read neither.
 *
 * Runs the SHIPPED route.ts with the database, the session and both
 * projections stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const rows: Record<string, Record<string, unknown>[]> = {
  customers: [
    { id: "c1", fullName: "Annika Rahman", email: "annika@rahman.co", taxId: "AB-99", passwordHash: "$2b$12$x" },
  ],
  bulletins: [{ id: "b1", title: "Open day" }],
  users: [{ id: "u1", email: "admin@example.com", password: "$2b$12$y" }],
};
const tables: Record<string, any> = {
  customers: { __name: "customers", id: 1, fullName: 1, email: 1, taxId: 1, passwordHash: 1 },
  bulletins: { __name: "bulletins", id: 1, title: 1 },
  users: { __name: "users", id: 1, email: 1, password: 1 },
};

// The session the route sees, swapped per case.
let session: any = null;

const db = {
  select: () => ({ from: (t: any) => ({ limit: async () => rows[t.__name] ?? [] }) }),
};

installHarness({
  stubs: {
    "@/db": "export const db = globalThis.__db;",
    "@/db/schema": "export const customers = globalThis.__tables.customers; export const bulletins = globalThis.__tables.bulletins; export const users = globalThis.__tables.users;",
    "@/auth": "export const auth = async () => globalThis.__session;",
    "@/lib/entity-access":
      "export const ENTITY_ACCESS = { customers: { read: ['Admin'], write: ['Admin'] }, bulletins: { read: ['*'], write: ['Admin'] } };",
    "@/lib/sensitive-columns":
      "export const SENSITIVE_COLUMNS = { Customer: { taxId: { mask: 'last4', readers: ['Admin'] } } };",
    "drizzle-orm":
      "export const getTableName = (t) => t.__name;" +
      "export const getTableColumns = (t) => Object.fromEntries(Object.entries(t).filter(([k]) => k !== '__name'));" +
      "export const is = (v) => !!v && typeof v === 'object' && '__name' in v;" +
      "export class Table {}",
  },
});
(globalThis as any).__db = db;
(globalThis as any).__tables = tables;

const { GET } = await import("../api-export/route.ts");
const call = (entity: string, who: any = null) => {
  (globalThis as any).__session = who;
  return GET(new Request(`http://app/api/export/${entity}`), {
    params: Promise.resolve({ entity }),
  });
};

// ── who may download it ───────────────────────────────────────────────────
let res = await call("customers");
eqJson(res.status, 401, "an anonymous caller is turned away from a private entity");

res = await call("customers", { user: { role: "Reception" } });
eqJson(res.status, 403, "a signed-in role that may not read it is turned away");

res = await call("customers", { user: { role: "Admin" } });
eqJson(res.status, 200, "the role the projection names may download it");

res = await call("bulletins");
eqJson(res.status, 200, "`*` in the read list is what a public page means — no session needed");

res = await call("nothing_like_this");
eqJson(res.status, 404, "an entity that does not exist is a 404");

// ── what the file may carry ───────────────────────────────────────────────
res = await call("customers", { user: { role: "Admin" } });
let csv = await res.text();
let header = csv.split("\n")[0];
ok(!header.includes("taxId"), "a DECLARED sensitive column is not in the file");
ok(!header.includes("passwordHash"), "a credential column is not in the file");
ok(!csv.includes("$2b$12$x"), "and its value is nowhere in the body");
eqJson(header, "id,fullName,email", "what is left is the owner's own data");
eqJson(res.headers.get("X-Forge-Withheld-Columns"), "taxId,passwordHash",
       "what was withheld is said, not silently dropped");

// The platform's `users` table is not a declared entity, so no projection
// covers it — the credential floor is what stops the hash going out.
res = await call("users", { user: { role: "Admin" } });
csv = await res.text();
eqJson(csv.split("\n")[0], "id,email", "an undeclared table still loses its password column");
ok(!csv.includes("$2b$12$y"), "no hash in the body either");

// ── the shape the import reads ────────────────────────────────────────────
res = await call("bulletins");
csv = await res.text();
eqJson(csv, "id,title\nb1,Open day\n", "headers are the schema's own names, one row per record");
done("export");
