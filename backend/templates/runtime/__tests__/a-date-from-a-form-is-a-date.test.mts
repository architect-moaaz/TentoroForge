/**
 * A date that arrives as text is saved as a date.
 *
 * A request body is JSON, so every date reaches the data engine as a string.
 * A date-mode column (`timestamp()`) is serialised by drizzle calling
 * `.toISOString()` on the value — on a string that throws "value.toISOString
 * is not a function", and every create of a record with such a field failed
 * through the data API (ToroCommerce's orders, torob1, 2026-10-09).
 *
 * Runs the SHIPPED data-engine.ts with REAL drizzle column types; the database
 * is a fake that serialises each value the way the driver does
 * (`mapToDriverValue`), which is where the failure happened.
 */
import { installHarness, eqJson, ok, done } from "./_harness.mts";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const NM = process.env.FORGE_NODE_MODULES!;

const rows: any[] = [];
const db = {
  insert: (table: any) => ({
    values: (v: any) => {
      // What the driver does with each value before it is sent.
      const sent: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v)) {
        const col = table[k];
        sent[k] = col && val !== null && val !== undefined && typeof col.mapToDriverValue === "function"
          ? col.mapToDriverValue(val) : val;
      }
      const row = { id: `row-${rows.length + 1}`, ...v, __sent: sent };
      rows.push(row);
      return { returning: async () => [row] };
    },
  }),
  select: () => ({ from: () => ({ where: () => ({ limit: async () => [] }), limit: async () => [] }) }),
};
(globalThis as any).__DB__ = db;

installHarness({
  stubs: {
    "@/db": "export const db = globalThis.__DB__;",
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "./integrations/resolver": "export const getSecret = async () => undefined;\n",
    "./storage": "export const loadFileBase64 = async () => null;\n",
    "./fk-roles": "export const FK_ROLES = {};\nexport const fkRole = () => undefined;\nexport const isDomainFk = () => false;\n",
    "./sensitive-columns": "export const sensitiveColumnsFor = () => ({});\n",
    "./searchable-columns": "export const searchableColumnsFor = () => [];\n",
    "./sensitive-crypto":
      "export const encryptSensitive = async (v) => v;\nexport const decryptSensitive = async (v) => v;\n" +
      "export const mask = (v) => v;\nexport const looksMasked = () => false;\n",
    "@/lib/rules":
      "export const filterFields = async (_e, r) => r;\n" +
      "export const validateEntity = async () => ({ valid: true, errors: [] });\n" +
      "export const evaluateRuleSet = async () => ({ errors: [], patches: {}, sideEffects: [] });\n" +
      "export const rowAccessRulesFor = async () => [];\n",
    "./events/bus": "export const emitEventAndProcess = async () => {};\n",
    "./ownership-rules": "export const ownershipRulesFor = () => [];\n",
  },
  redirect: {
    "drizzle-orm": join(NM, "drizzle-orm", "index.js"),
    "drizzle-orm/pg-core": join(NM, "drizzle-orm", "pg-core", "index.js"),
    "@/lib/rules/row-access-sql": join(HERE, "..", "rules", "row-access-sql.ts"),
  },
});

const { pgTable, uuid, text, timestamp } = await import("drizzle-orm/pg-core");
const orders = pgTable("orders", {
  id: uuid("id").primaryKey().defaultRandom(),
  number: text("number").notNull(),
  placedAt: timestamp("placed_at").notNull(),
  shippedAt: timestamp("shipped_at"),
});
const engine = await import("../data-engine.ts");
engine.registerEntity("orders", orders as any, { slug: "orders" });
const admin = { user: { id: "admin", role: "Admin" } };

let failed = "";
try {
  await engine.create("orders", { number: "ORD-1", placedAt: "2026-10-09T04:40:01.978Z", shippedAt: "" }, admin);
} catch (e: any) {
  failed = String(e?.message || e);
}
eqJson(failed, "", "an order whose date came as text is created");
const row = rows[0];
ok(row?.placedAt instanceof Date, "the date column receives a Date");
eqJson(row?.__sent?.placedAt, "2026-10-09T04:40:01.978Z", "and the driver sends the same moment");
eqJson(row?.shippedAt ?? null, null, "an empty date is no date, not an error");
done();
