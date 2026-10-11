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
    export const db = {
      async execute(q) {
        globalThis.__SQL__.push(q.text);
        if (q.text.includes("SELECT hash FROM forge_audit ORDER BY seq DESC")) {
          const last = globalThis.__ROWS__.at(-1); return last ? [{ hash: last.hash }] : [];
        }
        if (q.text.startsWith("\\n    INSERT INTO forge_audit")) {
          const v = q.values; const row = { seq: globalThis.__ROWS__.length + 1, at: v[0], actor_id: v[1], action: v[7],
            entity: v[8], entity_id: v[9], before: JSON.parse(v[10]), after: JSON.parse(v[11]), prev_hash: v[17], hash: v[18] };
          globalThis.__ROWS__.push(row); return [{ seq: row.seq, hash: row.hash }];
        }
        if (q.text.includes("FROM forge_audit ORDER BY seq ASC")) return globalThis.__ROWS__;
        return [];
      },
      async transaction(fn) { return fn(this); },
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
rows[0].after = { total: 99 };
eqJson(await audit.verifyChain(), { ok: false, checked: 1, brokenAt: 1 }, "a row changed underneath is found");

const big = "x".repeat(70_000);
const three = await audit.recordAudit((await import("@/db")).db, { action: "create", entity: "Note", entityId: "n", after: { body: big } });
ok(three && rows[2].after.truncated === true && rows[2].after.bytes > 64 * 1024, "a huge value is cut and says so");
done("every change is on the record");
