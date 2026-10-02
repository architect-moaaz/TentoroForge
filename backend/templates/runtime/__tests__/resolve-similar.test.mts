/**
 * Embedding fields end to end on a REAL Postgres with pgvector: the shipped
 * data-engine.ts and embeddings.ts, real drizzle, a real `vector(512)` column
 * behind a real HNSW index. Only the embedding model is faked — a fetch that
 * answers like the CLIP sidecar with a vector chosen by the image's content or
 * the query's words — so what is asserted is what the database ranked.
 *
 *   - create fills the embedding from the image field;
 *   - an edit that does not touch the image does not re-embed it; one that
 *     does, does;
 *   - resolveSimilar ranks by cosine distance, scores 0–100, keeps the
 *     reader's ownership scope, and never returns a vector;
 *   - text queries share the space; no query is no results; no service is an
 *     error that says so.
 *
 * Needs VECTOR_TEST_DATABASE_URL (a Postgres with pgvector available) and
 * FORGE_NODE_MODULES (a node_modules holding drizzle-orm and postgres — any
 * generated app's). Run via __tests__/run-similar-tests.sh.
 */

import { installHarness, eqJson, ok, throwsNamed, done } from "./_harness.mts";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const NM = process.env.FORGE_NODE_MODULES!;
const URL = process.env.VECTOR_TEST_DATABASE_URL!;

// ── The fake model: a direction per colour, so distances are known ───────────

const DIM = 512;
const AXIS: Record<string, number> = { red: 0, blue: 1, green: 2, crimson: 0 };
function unit(axis: number, tilt = 0): number[] {
  const v = new Array(DIM).fill(0);
  v[axis] = 1;
  if (tilt) v[(axis + 1) % 3] = tilt;           // a little of the next colour
  const n = Math.hypot(...v);
  return v.map((x) => x / n);
}
let modelCalls = 0;
let serviceUp = true;
globalThis.fetch = (async (_url: string, init: any) => {
  modelCalls++;
  const body = JSON.parse(init.body);
  let vector: number[];
  if (body.text) {
    const word = Object.keys(AXIS).find((w) => body.text.includes(w)) ?? "red";
    vector = unit(AXIS[word], 0.05);
  } else {
    const [colour, tilt] = Buffer.from(body.image_b64, "base64").toString().split(":");
    vector = unit(AXIS[colour], Number(tilt || 0));
  }
  return new Response(JSON.stringify({ vector, dimensions: DIM, model: "fake" }), { status: 200 });
}) as any;

// Stored files: the "image" bytes are the colour name, so the fake model can see them.
const FILES: Record<string, string> = {
  "00000000-0000-4000-8000-000000000001": "red:0",
  "00000000-0000-4000-8000-000000000002": "red:0.4",
  "00000000-0000-4000-8000-000000000003": "blue:0",
  "00000000-0000-4000-8000-000000000004": "green:0",
  "00000000-0000-4000-8000-000000000005": "red:0.1",   // the query image
};
(globalThis as any).__FILES__ = FILES;

const MANIFEST = JSON.stringify([
  { property: "photoEmbedding", column: "photo_embedding", of: "photo", source: "image" },
]);

installHarness({
  stubs: {
    "@/db": "export const db = globalThis.__DB__;",
    "./embedding-columns":
      "export const EMBEDDING_DIMENSIONS = 512;\n" +
      `export const embeddingColumnsFor = (e) => ['products', 'product', 'Product'].includes(e) ? ${MANIFEST} : [];\n`,
    "./integrations/resolver":
      "export const getSecret = async (_p, k) => k === 'EMBEDDINGS_URL' && globalThis.__SERVICE_UP__ !== false ? 'http://clip.test' : undefined;\n",
    "./storage":
      "export const loadFileBase64 = async (id) => globalThis.__FILES__[id] ? " +
      "{ base64: Buffer.from(globalThis.__FILES__[id]).toString('base64'), mediaType: 'image/png', filename: id + '.png' } : null;\n",
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
    // Each person sees their own products; an admin sees all of them.
    "./ownership-rules":
      "export const ownershipRulesFor = (e) => ['products', 'product', 'Product'].includes(e) ? " +
      "[{ column: 'ownerId', kind: 'scope', scope: 'user', unscopedRoles: ['admin'] }] : [];\n",
  },
  redirect: {
    "drizzle-orm": join(NM, "drizzle-orm", "index.js"),
    "drizzle-orm/pg-core": join(NM, "drizzle-orm", "pg-core", "index.js"),
    "drizzle-orm/postgres-js": join(NM, "drizzle-orm", "postgres-js", "index.js"),
    "postgres": join(NM, "postgres", "src", "index.js"),
    "@/lib/rules/row-access-sql": join(HERE, "..", "rules", "row-access-sql.ts"),
  },
});

const postgres = (await import("postgres")).default;
const { drizzle } = await import("drizzle-orm/postgres-js");
const { pgTable, uuid, text, vector, index } = await import("drizzle-orm/pg-core");

const client = postgres(URL, { max: 2, onnotice: () => {} });
await client.unsafe("CREATE EXTENSION IF NOT EXISTS vector");
await client.unsafe("DROP TABLE IF EXISTS products");
await client.unsafe(`CREATE TABLE products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  photo text,
  owner_id text,
  photo_embedding vector(512),
  updated_at timestamp
)`);
await client.unsafe(
  "CREATE INDEX products_photo_embedding_hnsw ON products USING hnsw (photo_embedding vector_cosine_ops)");

// The table as the projection emits it.
const products = pgTable("products", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: text("name").notNull(),
  photo: text("photo"),
  ownerId: text("owner_id"),
  photoEmbedding: vector("photo_embedding", { dimensions: 512 }),
  updatedAt: text("updated_at"),
}, (t) => [index("products_photo_embedding_hnsw").using("hnsw", t.photoEmbedding.op("vector_cosine_ops"))]);

(globalThis as any).__DB__ = drizzle(client);
const engine = await import("../data-engine.ts");
engine.registerEntity("products", products as any, { slug: "products" });

const alice = { user: { id: "alice", role: "member" } };
const bob = { user: { id: "bob", role: "member" } };
const admin = { user: { id: "root", role: "admin" } };

const stored = async (id: string) =>
  (await client`SELECT photo_embedding IS NOT NULL AS has, photo_embedding::text AS v FROM products WHERE id = ${id}`)[0];

console.log("create fills the embedding");
const red = (await engine.create("products", { name: "Red chair", photo: "00000000-0000-4000-8000-000000000001" }, alice)).data;
const pink = (await engine.create("products", { name: "Pinkish chair", photo: "00000000-0000-4000-8000-000000000002" }, alice)).data;
const blue = (await engine.create("products", { name: "Blue chair", photo: "00000000-0000-4000-8000-000000000003" }, alice)).data;
const green = (await engine.create("products", { name: "Green chair", photo: "00000000-0000-4000-8000-000000000004" }, alice)).data;
const bobsRed = (await engine.create("products", { name: "Bob's red chair", photo: "00000000-0000-4000-8000-000000000001" }, bob)).data;
const bare = (await engine.create("products", { name: "No photo yet" }, alice)).data;
ok((await stored(red.id)).has, "a product created with a photo has its embedding");
ok(!(await stored(bare.id)).has, "a product with no photo has none");
eqJson(modelCalls, 5, "the model ran once per photo, not for the product without one");
ok(!("photoEmbedding" in red), "create answers without the vector");

console.log("\nedits re-embed only when the photo changes");
const before = (await stored(red.id)).v;
modelCalls = 0;
await engine.update("products", red.id, { name: "Red armchair" }, alice);
eqJson(modelCalls, 0, "renaming does not call the model");
eqJson((await stored(red.id)).v, before, "and leaves the embedding as it was");
await engine.update("products", blue.id, { photo: "00000000-0000-4000-8000-000000000004" }, alice);
eqJson(modelCalls, 1, "a new photo is embedded");
await engine.update("products", blue.id, { photo: "00000000-0000-4000-8000-000000000003" }, alice);
modelCalls = 0;

console.log("\nresolveSimilar ranks by what the image looks like");
const hits = await engine.resolveSimilar(
  { op: "similar", entity: "products", field: "photoEmbedding" },
  { image: "00000000-0000-4000-8000-000000000005" }, alice);
eqJson(hits.map((h: any) => h.name), ["Red armchair", "Pinkish chair", "Blue chair", "Green chair"],
  "closest first: red, then pinkish, then the rest");
ok(hits[0].similarity >= 99 && hits[0].similarity <= 100, `the red chair scores ~100 (${hits[0].similarity})`);
ok(hits[1].similarity < hits[0].similarity && hits[1].similarity > hits[2].similarity,
  `the pinkish chair sits between (${hits.map((h: any) => h.similarity).join(", ")})`);
ok(hits.every((h: any) => !("photoEmbedding" in h)), "no hit carries its vector");
ok(!hits.some((h: any) => h.id === bobsRed.id), "Bob's product is not in Alice's results");
ok(!hits.some((h: any) => h.id === bare.id), "a product with no embedding is not ranked");

const asAdmin = await engine.resolveSimilar(
  { op: "similar", entity: "products" }, { image: "00000000-0000-4000-8000-000000000005" }, admin);
ok(asAdmin.some((h: any) => h.id === bobsRed.id), "an admin's results include Bob's product");
eqJson((await engine.resolveSimilar({ op: "similar", entity: "products", limit: 2 },
  { image: "00000000-0000-4000-8000-000000000005" }, admin)).length, 2, "limit caps the results");

console.log("\ntext shares the space");
const byWords = await engine.resolveSimilar({ op: "similar", entity: "products" }, { text: "something green" }, alice);
eqJson(byWords[0]?.name, "Green chair", "\"something green\" finds the green chair first");

console.log("\nno query, no service");
eqJson(await engine.resolveSimilar({ op: "similar", entity: "products" }, {}, alice), [], "no query is no results");
(globalThis as any).__SERVICE_UP__ = false;
await throwsNamed(() => engine.resolveSimilar({ op: "similar", entity: "products" }, { text: "red" }, alice),
  "EmbeddingUnavailable", "an unconnected service is an error that says so, not an empty list");
const offline = (await engine.create("products", { name: "Offline chair", photo: "00000000-0000-4000-8000-000000000001" }, alice)).data;
ok(offline?.id && !(await stored(offline.id)).has, "a write still lands when the service is down; its vector waits");
(globalThis as any).__SERVICE_UP__ = true;
await engine.update("products", offline.id, { name: "Offline chair, back" }, alice);
ok((await stored(offline.id)).has, "the next write of that row fills the missing vector");
await throwsNamed(() => engine.resolveSimilar({ op: "similar", entity: "products", field: "nope" }, { text: "red" }, alice),
  "Error", "ranking by a field that is not an embedding is refused by name");

console.log("\nreads never carry vectors");
const listed = await engine.query("products", { limit: 50 }, admin);
ok(listed.data.length >= 6 && listed.data.every((r: any) => !("photoEmbedding" in r)), "a list has no vectors");
const one = await engine.findById("products", green.id, alice);
ok(one && !("photoEmbedding" in one), "a single record has no vector");

await client.unsafe("DROP TABLE products");
await client.end();
done("resolve-similar");
