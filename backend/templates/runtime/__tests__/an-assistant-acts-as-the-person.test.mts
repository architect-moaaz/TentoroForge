/**
 * The SHIPPED lib/mcp/protocol.ts and app/api/mcp/route.ts: an assistant with
 * a person's token sees the tools that person's role may use, and each tool
 * calls the route a screen calls, signed in as them; off is 404; no token,
 * or a revoked one, is 401.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const CATALOG = {
  app: "Shop", about: "A clothes shop",
  workflows: [
    { tool: "add_to_cart", id: "FLOW-018", name: "Add to Cart", description: "Add to Cart: a variant into the cart",
      roles: ["*"], inputSchema: { type: "object", properties: { productVariant: { type: "string" } }, required: ["productVariant"] } },
    { tool: "add_product", id: "FLOW-023", name: "Add Product", description: "Add Product", roles: ["Admin"],
      inputSchema: { type: "object", properties: {}, required: [] } },
  ],
  records: [
    { slug: "products", name: "Product", description: "", find: "find_products", get: "get_products",
      fields: [{ name: "id", type: "uuid" }, { name: "name", type: "string" }], roles: ["*", "Admin", "Customer"] },
    { slug: "orders", name: "Order", description: "", find: "find_orders", get: "get_orders",
      fields: [{ name: "id", type: "uuid" }], roles: ["Admin"] },
  ],
};

installHarness({
  stubs: {
    "next/server": `export class NextResponse extends Response {
      static json(body, init = {}) { return new Response(JSON.stringify(body), { ...init, headers: { "content-type": "application/json", ...(init.headers || {}) } }); }
    }`,
    "@/lib/mcp/catalog.json": `export default ${JSON.stringify(CATALOG)};`,
    "@/lib/mcp/tokens": `export async function personOf(t) { return t === "fmcp_good" ? "u-1" : t === "fmcp_admin" ? "u-2" : null; }`,
    "@/lib/mcp/session": `export async function signIn(id) {
      return id === "u-1" ? { cookie: "forge-x.session-token=JWT1", person: { id, role: "Customer", email: "c@shop.test" } }
           : { cookie: "forge-x.session-token=JWT2", person: { id, role: "Admin", email: "a@shop.test" } }; }`,
  },
  redirect: { "@/lib/mcp/protocol": new URL("../../app-foundation/src/lib/mcp/protocol.ts", import.meta.url).pathname },
});

const protocol: any = await import("../../app-foundation/src/lib/mcp/protocol.ts");
const customer = { id: "u-1", role: "Customer" };
const names = (tools: any[]) => tools.map((t) => t.name).sort();
eqJson(names(protocol.toolsFor(CATALOG, customer)), ["add_to_cart", "find_products", "get_products"],
       "a customer sees what a customer may use");
eqJson(names(protocol.toolsFor(CATALOG, { id: "u-2", role: "Admin" })).length, 6, "the admin sees all six");
ok(protocol.toolsFor(CATALOG, customer).find((t: any) => t.name === "find_products").annotations.readOnlyHint,
   "a read is marked as only looking");

const calls: any[] = [];
const doors = {
  run: async (id: string, input: any) => { calls.push(["run", id, input]); return { status: 200, body: { status: "completed", reply: { cart: "c-9" } } }; },
  read: async (slug: string, id: string | null, q: any) => { calls.push(["read", slug, id, q]); return { status: 403, body: { error: "Forbidden" } }; },
};
const init = await protocol.handle({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26" } }, CATALOG, customer, doors);
eqJson(init.result.protocolVersion, "2025-03-26", "the client's protocol version is answered in kind");
ok(init.result.capabilities.tools && init.result.serverInfo.name === "Shop", "it offers tools, under the app's name");
const ran = await protocol.handle({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "add_to_cart", arguments: { productVariant: "v-1" } } }, CATALOG, customer, doors);
eqJson(calls[0], ["run", "FLOW-018", { productVariant: "v-1" }], "a workflow tool runs that workflow with the arguments");
ok(!ran.result.isError && ran.result.structuredContent.reply.cart === "c-9", "what the run answered comes back");
const refused = await protocol.handle({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "find_products", arguments: { search: "linen", filters: { category: "Tops" }, limit: 500 } } }, CATALOG, customer, doors);
eqJson(calls[1], ["read", "products", null, { search: "linen", page: "1", limit: "100", category: "Tops" }],
       "a find reads the data route: search, filters, a capped page");
ok(refused.result.isError && /role may not/.test(refused.result.content[0].text), "the route's refusal is said as one");
const hidden = await protocol.handle({ jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "add_product", arguments: {} } }, CATALOG, customer, doors);
ok(hidden.result.isError && calls.length === 2, "a tool the role may not use is refused before anything runs");
eqJson((await protocol.handle({ jsonrpc: "2.0", id: 5, method: "tools/call", params: { name: "nope" } }, CATALOG, customer, doors)).error.code,
       -32602, "an unknown tool is an error");
eqJson(await protocol.handle({ jsonrpc: "2.0", method: "notifications/initialized" }, CATALOG, customer, doors), null,
       "a notification has no reply");

// --- the route ---------------------------------------------------------------
const route: any = await import("../../app-foundation/src/app/api/mcp/route.ts");
const fetched: any[] = [];
(globalThis as any).fetch = async (url: string, init: any) => {
  fetched.push({ url, init });
  return new Response(JSON.stringify({ status: "completed", reply: {} }), { status: 200 });
};
const post = (body: any, token?: string) => route.POST(new Request("http://localhost:3100/api/mcp", {
  method: "POST", headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
  body: JSON.stringify(body) }));

process.env.FORGE_APP_MCP = "off";
eqJson((await post({ jsonrpc: "2.0", id: 1, method: "tools/list" }, "fmcp_good")).status, 404, "off: not found");
process.env.FORGE_APP_MCP = "on";
const anon = await post({ jsonrpc: "2.0", id: 1, method: "tools/list" });
ok(anon.status === 401 && /Bearer/.test(anon.headers.get("www-authenticate") ?? ""), "no token: 401, asking for one");
eqJson((await post({ jsonrpc: "2.0", id: 1, method: "tools/list" }, "fmcp_revoked")).status, 401, "a token nobody holds: 401");
const listed = await (await post({ jsonrpc: "2.0", id: 1, method: "tools/list" }, "fmcp_good")).json();
eqJson(names(listed.result.tools), ["add_to_cart", "find_products", "get_products"], "the token's person's tools");
await post({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "add_to_cart", arguments: { productVariant: "v-1" } } }, "fmcp_good");
eqJson(fetched[0].url, "http://localhost:3100/api/workflows/FLOW-018/execute", "the workflow route, on the app's own address");
eqJson(fetched[0].init.headers.cookie, "forge-x.session-token=JWT1", "signed in as the token's person");
eqJson(JSON.parse(fetched[0].init.body), { input: { productVariant: "v-1" } }, "the arguments as the run's input");
await post({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "get_orders", arguments: { id: "o-7" } } }, "fmcp_admin");
eqJson(fetched[1].url, "http://localhost:3100/api/data/orders/o-7", "a get reads one record from the data route");
eqJson((await post({ jsonrpc: "2.0", method: "notifications/initialized" }, "fmcp_good")).status, 202, "a notification: accepted, no body");
eqJson((await route.GET()).status, 405, "no stream: GET is not allowed");

done();
