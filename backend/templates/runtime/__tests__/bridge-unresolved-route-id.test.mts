/**
 * A detail/action route reached at its literal template
 * (`/rentals/[id]/return`, id="[id]") — no real record selected — passed "[id]"
 * straight to a get-by-id, and Postgres rejected it as an invalid uuid, failing
 * the whole page with a 500 instead of a "not found" state. The bridge now
 * treats an id still carrying the `[…]` placeholder as no record: no query.
 *
 * Runs the SHIPPED data-engine-bridge.ts against a stub engine that records
 * every findById it is asked for.
 */
import { installHarness, eqJson, done } from "./_harness.mts";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const BRIDGE = join(HERE, "..", "..", "app-foundation", "src", "lib", "data-engine-bridge.ts");

(globalThis as any).__FINDS__ = [];
installHarness({
  stubs: {
    "./data-engine":
      "export async function query() { return { data: [], total: 0 }; }\n" +
      "export async function findById(entity, id) { globalThis.__FINDS__.push({entity, id}); return { id }; }\n" +
      "export async function resolveAggregate() { return {}; }\n" +
      "export async function resolveSeries() { return []; }\n" +
      "export async function resolveQuery() { return []; }\n" +
      "export async function resolveSimilar() { return []; }\n" +
      "export function getEntity() { return undefined; }\n" +
      "export function registerEntity() {}\n",
    "./data-init": "export async function ensureDataEngineInitialized() {}\n",
    "@tentoroforge/renderer": "export {};\n",
  },
});

const { dataEngine } = await import(BRIDGE);
const finds = (globalThis as any).__FINDS__ as any[];

console.log("an unresolved route id on the source is not sent to the database");
{
  const r = await dataEngine.run({ name: "rentals", entity: "Rental", op: "get", id: "[id]" });
  eqJson(r, [], "no record — a placeholder id is not queried");
  eqJson(finds.length, 0, "findById was never called with the placeholder");
}

console.log("an unresolved route id from the request URL is not sent to the database");
{
  const r = await dataEngine.run(
    { name: "rentals", entity: "Rental", op: "get" },
    { request: new Request("http://app.local/p/x/rentals/%5Bid%5D/return?id=%5Bid%5D") },
  );
  eqJson(r, [], "no record — the literal [id] from the URL is not queried");
  eqJson(finds.length, 0, "findById still never called");
}

console.log("a real id IS fetched");
{
  const r = await dataEngine.run({ name: "rentals", entity: "Rental", op: "get", id: "a3f1c0de-0000-4000-8000-000000000001" });
  eqJson(finds.at(-1).id, "a3f1c0de-0000-4000-8000-000000000001", "a valid id reaches findById");
  eqJson(Array.isArray(r) && r.length === 1, true, "and returns the record");
}

done("bridge-unresolved-route-id");
