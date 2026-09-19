/**
 * A list source scoped to the signed-in user's own row —
 * `filter: {propertyId: "{{user.homePropertyId}}"}` — resolves in the bridge,
 * before anything renders, so the renderer's interpolation never sees it.
 * Nothing filled the placeholder and the engine compared propertyId to the
 * literal text: an empty sign-offs queue for every approver.
 *
 * Runs the SHIPPED data-engine-bridge.ts against a stub engine that records
 * the filters it was asked for.
 */
import { installHarness, eqJson, done } from "./_harness.mts";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const BRIDGE = join(HERE, "..", "..", "app-foundation", "src", "lib", "data-engine-bridge.ts");

(globalThis as any).__QUERIES__ = [];
installHarness({
  stubs: {
    "./data-engine":
      "export async function query(entity, opts, ctx) { globalThis.__QUERIES__.push({entity, filters: opts?.filters ?? null, ctx}); return { data: [], total: 0 }; }\n" +
      "export async function findById() { return null; }\n" +
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
const source = { name: "queueCases", entity: "RefundCase", op: "list",
                 filter: { propertyId: "{{user.homePropertyId}}", status: "Pending approval" } };
const queries = (globalThis as any).__QUERIES__ as any[];

console.log("a {{user.<column>}} filter is filled from the session user");
{
  await dataEngine.run(source, { user: { id: "u1", role: "Front Office Manager", homePropertyId: "prop-st-giles" } });
  eqJson(queries.at(-1).filters, { propertyId: "prop-st-giles", status: "Pending approval" },
    "the approver's home property is the value compared");
}

console.log("a user without the column is not narrowed by it");
{
  // "scoped to their home property where they have one": Finance has none
  // and reads the chain. The ownership rules stay the boundary — a scoped
  // role with no home property reads nothing there. Left as text, the
  // placeholder reached Postgres as a uuid and the whole source failed.
  await dataEngine.run(source, { user: { id: "u2", role: "Finance" } });
  eqJson(queries.at(-1).filters, { status: "Pending approval" },
    "the filter naming the missing column is dropped; the rest stays");
}

console.log("a literal filter is untouched");
{
  await dataEngine.run({ ...source, filter: { status: "Issued" } }, { user: { id: "u1", role: "CEO" } });
  eqJson(queries.at(-1).filters, { status: "Issued" }, "no placeholder, no change");
}

done("bridge-user-filter");
