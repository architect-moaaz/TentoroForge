/**
 * The trail: a row chained to the one before, verifiable, and written only
 * when a policy says so. Runs the SHIPPED audit.ts against a stub database
 * that records what it was asked and answers the previous hash.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

(globalThis as any).__SQL__ = [];
(globalThis as any).__ROWS__ = [];
installHarness({ stubs: {
  "drizzle-orm": `
    const tag = (strings, ...values) => ({ strings: [...strings], values, text: strings.join("?") });
    tag.raw = (s) => ({ strings: [s], values: [], text: s });
    tag.join = (parts, sep) => ({ strings: [], values: parts, text: parts.map((p) => p.text).join(sep?.text ?? ",") });
    export const sql = tag;`,
  "@/db": `
    // AS POSTGRES HANDS JSONB BACK: keys shortest first, then by bytes.
    const order = (v) => Array.isArray(v) ? v.map(order) : (v && typeof v === "object")
      ? Object.fromEntries(Object.keys(v).sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0)).map((k) => [k, order(v[k])]))
      : v;
    const jsonb = (text) => order(JSON.parse(text));
    export const db = globalThis.__fakeDb = {
      async execute(q) {
        globalThis.__SQL__.push(q.text);
        if (q.text.includes("SELECT hash FROM forge_audit ORDER BY seq DESC")) {
          const last = globalThis.__ROWS__.at(-1); return last ? [{ hash: last.hash }] : [];
        }
        if (q.text.startsWith("\\n    INSERT INTO forge_audit")) {
          // one row, or a batch: VALUES joined from one fragment per row (recordAuditMany)
          const batch = q.values.length === 1 && Array.isArray(q.values[0]?.values) && q.values[0].values[0]?.values
            ? q.values[0].values.map((f) => f.values) : [q.values];
          let last;
          for (const v of batch) {
            const row = { seq: globalThis.__ROWS__.length + 1, at: v[0], actor_id: v[1], action: v[7],
              entity: v[8], entity_id: v[9], before: jsonb(v[10]), after: jsonb(v[11]), prev_hash: v[17], hash: v[18] };
            globalThis.__ROWS__.push(row); last = row;
          }
          return [{ seq: last.seq, hash: last.hash }];
        }
        if (q.text.includes("FROM forge_audit ORDER BY seq ASC")) return globalThis.__ROWS__.slice(0, q.values?.[0] ?? undefined);
        if (q.text.includes("WHERE action = 'prune'"))
          return globalThis.__ROWS__.filter((r) => r.action === "prune" && r.prev_hash != null).map((r) => ({ prev_hash: r.prev_hash }));
        return [];
      },
      async transaction(fn) { globalThis.__TX__ = (globalThis.__TX__ ?? 0) + 1; return fn(this); },
    };`,
  "./audit-policy": `export const AUDIT = { level: "regulated", reviewers: ["Compliance"], retentionDays: 30, reasonRequired: ["invoices"] };`,
} });

const audit: any = await import("../audit.ts");
await audit.ready();
ok(audit.auditOn() && audit.regulated(), "the policy is read");
ok(audit.reasonRequired("Invoices") && !audit.reasonRequired("orders"), "the records that need a reason, any case");
eqJson(audit.changedColumns({ a: 1, b: 2, updatedAt: 1 }, { a: 1, b: 3, updatedAt: 2 }), ["b"], "what changed, never the timestamp");

const one = await audit.recordAudit((await import("@/db")).db, { action: "create", entity: "Invoice", entityId: "i-1", after: { total: 10 }, actor: { id: "u-1", role: "Clerk" } });
const two = await audit.recordAudit((await import("@/db")).db, { action: "update", entity: "Invoice", entityId: "i-1", before: { total: 10 }, after: { total: 12 }, actor: { id: "u-1", role: "Clerk" }, reason: "corrected" });
ok(one && two, "two rows were written");
const rows = (globalThis as any).__ROWS__;
eqJson(rows[0].prev_hash, null, "the first row chains to nothing");
eqJson(rows[1].prev_hash, rows[0].hash, "the second row chains to the first");
ok((globalThis as any).__SQL__.some((s: string) => s.includes("pg_advisory_xact_lock")), "writers are serialised");
ok((globalThis as any).__SQL__.some((s: string) => s.includes("forge_audit is append-only")), "the guard is applied");
eqJson(await audit.verifyChain(), { ok: true, checked: 2 }, "the chain verifies");
// A REAL CHANGE: several fields, in the order a row has them, and a moment.
const three0 = await audit.recordAudit((await import("@/db")).db, { action: "create", entity: "Submission", entityId: "s-1",
  after: { submittedAt: new Date("2026-10-12T10:00:00Z"), fullName: "••••", id: "s-1", status: "New" }, actor: { id: "u-1" } });
ok(three0 && Object.keys(rows[2].after)[0] === "id", "the stub hands the row back reordered, as jsonb does");
eqJson(await audit.verifyChain(), { ok: true, checked: 3 }, "a change with many fields still verifies after the database reorders it");
ok(String(rows[2].hash).startsWith(audit.HASH_FORM), "a new row says how it was hashed");
rows.splice(2, 1);
rows[0].after = { total: 99 };
eqJson(await audit.verifyChain(), { ok: false, checked: 1, brokenAt: 1 }, "a row changed underneath is found");

const big = "x".repeat(70_000);
const three = await audit.recordAudit((await import("@/db")).db, { action: "create", entity: "Note", entityId: "n", after: { body: big } });
ok(three && rows[2].after.truncated === true && rows[2].after.bytes > 64 * 1024, "a huge value is cut and says so");
// WHAT A READ SAW, IN ONE STATEMENT (17 Nov 2026): a batch chains row to row and to the trail before it, keeps each
// row's record id, and takes the lock and the chain's last hash once.
rows.length = 0; (globalThis as any).__SQL__.length = 0;
const lead = await audit.recordAudit((await import("@/db")).db, { action: "create", entity: "Guest", entityId: "g-0", after: { fullName: "x" } });
const sqlBefore = (globalThis as any).__SQL__.length;
const n = await audit.recordAuditMany((await import("@/db")).db, ["g-1", "g-2", "g-3"].map((id) => ({
  action: "read_sensitive", entity: "Guest", entityId: id, changed: ["fullName", "email"], actor: { id: "u-2", role: "Requester" } })));
const batchSql = (globalThis as any).__SQL__.slice(sqlBefore);
ok(lead && n === 3 && rows.length === 4, "three reads were written as three rows");
eqJson(rows.map((r: any) => r.entity_id), ["g-0", "g-1", "g-2", "g-3"], "each row keeps the record it was about");
eqJson(rows.slice(1).map((r: any) => r.prev_hash), rows.slice(0, 3).map((r: any) => r.hash), "each row chains to the one before it");
eqJson(batchSql.filter((t: string) => t.includes("pg_advisory_xact_lock")).length, 1, "one lock for the batch");
eqJson(batchSql.filter((t: string) => t.includes("INSERT INTO forge_audit")).length, 1, "one statement for the batch");
eqJson(await audit.verifyChain(), { ok: true, checked: 4 }, "a batch verifies as the rows written one by one do");
eqJson(await audit.recordAuditMany((await import("@/db")).db, []), 0, "nothing seen, nothing written");
// THE LOCK HOLDS: on the bare connection the lock, the last hash and the insert run in one transaction; given a
// write's own transaction, the entry rides in it and opens no other.
const tx0 = (globalThis as any).__TX__ ?? 0;
await audit.recordAudit((await import("@/db")).db, { action: "login", entity: "users", entityId: "u-9" });
await audit.recordAuditMany((await import("@/db")).db, [{ action: "read_sensitive", entity: "Guest", entityId: "g-9", changed: ["email"] }]);
eqJson(((globalThis as any).__TX__ ?? 0) - tx0, 2, "each write on the bare connection takes its own transaction");
const tx1 = (globalThis as any).__TX__;
await audit.recordAudit({ execute: (q: any) => (globalThis as any).__fakeDb.execute(q) }, { action: "create", entity: "Note", entityId: "n-9" });
eqJson((globalThis as any).__TX__, tx1, "inside a write's transaction it opens no other");
// A PRUNED TRAIL STILL VERIFIES (18 Nov 2026): forge_audit_prune removes the oldest rows and appends a row naming
// the last hash it removed — after the rows it kept. Walking from the oldest, the first kept row links to a removed
// one; that is where the prune cut, not a break. Every pruned trail read as broken before.
rows.length = 0;
for (const id of ["p-1", "p-2", "p-3", "p-4"]) {
  await audit.recordAudit((await import("@/db")).db, { action: "create", entity: "Note", entityId: id, after: { id } });
}
const cut = rows.splice(0, 2);
rows.forEach((r: any, i: number) => { r.seq = i + 3; });
rows.push({ seq: 5, at: new Date().toISOString(), action: "prune", entity: "forge_audit", entity_id: null, actor_id: null,
  before: null, after: { removed: 2, lastHash: cut[1].hash }, prev_hash: cut[1].hash, hash: "prune-hash-1" });
eqJson(await audit.verifyChain(), { ok: true, checked: 3 }, "a pruned trail verifies from where the prune cut");
await audit.recordAudit((await import("@/db")).db, { action: "create", entity: "Note", entityId: "p-5", after: { id: "p-5" } });
eqJson(rows.at(-1).prev_hash, "prune-hash-1", "a row written after the prune chains to it");
eqJson(await audit.verifyChain(), { ok: true, checked: 4 }, "and the trail verifies past the prune");
eqJson(await audit.verifyChain(2), { ok: true, checked: 2 }, "a walk that stops before the prune row still knows where it cut");
rows[0].prev_hash = "not-a-removed-row";
eqJson(await audit.verifyChain(), { ok: false, checked: 1, brokenAt: 3 }, "a first row that links to nothing a prune removed is a break");
rows[0].prev_hash = cut[1].hash;
rows[1].prev_hash = cut[0].hash;
eqJson(await audit.verifyChain(), { ok: false, checked: 2, brokenAt: 4 }, "only the first kept row may start at the cut");

done("every change is on the record");
