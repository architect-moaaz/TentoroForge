/**
 * The SHIPPED /api/read/<op> route: each op is one function of the SDK's server
 * half, called with what the body says and answered as the page gets it. An
 * entity the application does not have is not read; a body that is not a
 * request is refused; a write is not here at all.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { resolve } from "node:path";

const geo = resolve(import.meta.dirname, "../../app-foundation/src/sdk/geo.ts");

installHarness({
  stubs: {
    "next/server": `export const NextResponse = { json: (body, init) => Response.json(body, init) };`,
    // Order: any signed-in person (and the Admin); Audit: the Admin's alone; Tool: a public page reads it. A column that is
    // not listed (a password hash, say) is not readable, and none of these lists it.
    "@/sdk/schema": `
      export const READABLE_FIELDS = {
        Order: ["id", "total", "status", "placedAt"], Tool: ["id", "name", "where"], Audit: ["id", "action"],
      };
      export const READ_ACCESS = {
        entities: {
          Order: { anyone: false, signedIn: true, roles: ["Admin"] },
          Tool: { anyone: true, signedIn: false, roles: ["Admin"] },
          Audit: { anyone: false, signedIn: false, roles: ["Admin"] },
        },
        widgets: {
          "WID-001": { anyone: false, signedIn: true, roles: ["Admin"] },
          "WID-002": { anyone: false, signedIn: false, roles: ["Admin"] },
        },
      };`,
    "@/sdk/widgets": `export const widgets = {
      revenue: { id: "WID-001", source: { op: "query", entity: "Order" } },
      audits: { id: "WID-002", source: { op: "query", entity: "Audit" } },
    };`,
    "@/sdk/server": `
      export const calls = [];
      const rec = (name, out) => async (...args) => { calls.push([name, ...args]); return typeof out === "function" ? out(...args) : out; };
      let who = { id: "u1", name: "Ann", email: "a@x.io", role: "Admin" };
      export const setUser = (u) => { who = u; };
      export const currentUser = rec("currentUser", () => who);
      export const myAccount = rec("myAccount", { id: "u1" });
      export const listPage = rec("listPage", (entity, o) => ({ rows: [{ id: "o1" }], total: 1, page: o.page ?? 1, limit: o.limit ?? 50 }));
      export const record = rec("record", (entity, id) => (id === "o1" ? { id: "o1", total: 12 } : null));
      export const recordsById = rec("recordsById", { o1: { id: "o1" } });
      export const count = rec("count", 7);
      export const total = rec("total", 99.5);
      export const series = rec("series", [{ label: "2026-01", value: 3 }]);
      export const query = rec("query", [{ revenue: 10 }]);
      export const runWidget = rec("runWidget", { rows: [], value: 4, previous: 2, delta: 1 });
      export const similar = rec("similar", { rows: [], error: null });
      export const near = rec("near", [{ id: "t1", distanceKm: 1.2 }]);
    `,
  },
  redirect: { "@/sdk/geo": geo },
});

const route: any = await import("../../../templates/app-foundation/src/app/api/read/[op]/route.ts");
const sdk: any = await import("@/sdk/server");

async function post(op: string, body: unknown) {
  sdk.calls.length = 0;
  const req = new Request(`http://app/api/read/${op}`, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body) });
  const res: Response = await route.POST(req, { params: Promise.resolve({ op }) });
  // The route asks who the person is before it reads: that lookup is not one of the reads these checks look at.
  return { status: res.status, json: await res.json(), calls: sdk.calls.filter((c: unknown[]) => c[0] !== "currentUser") };
}

let r = await post("list", { entity: "Order", where: { status: "open" }, limit: 500, page: 2, sort: "total", order: "asc" });
eqJson([r.status, r.json.total], [200, 1], "list answers the SDK's page");
eqJson(r.calls[0], ["listPage", "Order", { where: { status: "open" }, search: undefined, sort: "total", order: "asc", limit: 500, page: 2 }], "list hands the SDK the asked options (it clamps the size)");

r = await post("list", { entity: "Order", order: "sideways", limit: "ten" });
eqJson(r.calls[0][2].order, undefined, "an order that is not asc or desc is dropped");
eqJson(r.calls[0][2].limit, undefined, "a limit that is not a number is dropped");

r = await post("record", { entity: "Order", id: "o1" });
eqJson([r.status, r.json.record?.id], [200, "o1"], "a record that exists");
r = await post("record", { entity: "Order", id: "nope" });
eqJson([r.status, r.json.error?.code], [404, "NOT_FOUND"], "a record that is not there, or not yours, is a 404");

r = await post("records", { entity: "Order", ids: ["o1", 5, null] });
eqJson(r.calls[0], ["recordsById", "Order", ["o1"]], "only string ids are asked for");

r = await post("count", { entity: "Order", where: { status: "open" } });
eqJson([r.json.value, r.calls[0][0]], [7, "count"], "count");

r = await post("total", { entity: "Order", fn: "sum", field: "total" });
eqJson(r.json.value, 99.5, "total");
r = await post("total", { entity: "Order", fn: "median", field: "total" });
eqJson([r.status, r.json.error?.code], [400, "BAD_REQUEST"], "an aggregate the SDK does not have is refused");
r = await post("total", { entity: "Order", fn: "sum" });
eqJson(r.status, 400, "total needs a field");

r = await post("series", { entity: "Order", groupBy: "placedAt", bucket: "month", fn: "sum", field: "total" });
eqJson([r.json.points?.length, r.calls[0][2].bucket], [1, "month"], "series");
r = await post("series", { entity: "Order", groupBy: "placedAt", bucket: "decade" });
eqJson(r.calls[0][2].bucket, undefined, "a bucket the SDK does not have is dropped");
r = await post("series", { entity: "Order" });
eqJson(r.status, 400, "series needs groupBy");

r = await post("query", { entity: "Order", measures: { revenue: { fn: "sum", field: "total" } }, limit: 99999 });
eqJson([r.json.rows[0].revenue, r.calls[0][2].limit], [10, 1000], "query, and its top-N is held to 1000");
r = await post("query", { entity: "Order", measures: {} });
eqJson(r.status, 400, "query needs a measure");

r = await post("widget", { id: "WID-001", range: { from: "2026-01-01", to: "2026-02-01" } });
eqJson([r.json.value, r.json.delta], [4, 1], "a widget, with its change on the period before");
r = await post("widget", { id: "WID-404" });
eqJson(r.status, 404, "a widget the Blueprint does not have");

r = await post("similar", { entity: "Tool", text: "drill" });
eqJson([r.status, r.json.error], [200, null], "similar");

r = await post("near", { entity: "Tool", field: "where", from: "51.5,-0.12", radiusKm: 5 });
eqJson(r.calls[0][3], { lat: 51.5, lng: -0.12 }, "near reads 'lat,lng'");
r = await post("near", { entity: "Tool", field: "where", from: { lat: 1, lng: 2 } });
eqJson(r.calls[0][3], { lat: 1, lng: 2 }, "near reads a point");
r = await post("near", { entity: "Tool", field: "where", from: { lat: "x" } });
eqJson(r.calls[0][3], null, "a point that is not one ranks nothing");

r = await post("list", { entity: "constructor" });
eqJson([r.status, r.json.error?.code], [404, "UNKNOWN_ENTITY"], "an inherited name is not an entity");
r = await post("list", { entity: "Nope" });
eqJson(r.status, 404, "an entity the application does not have");
r = await post("list", { });
eqJson(r.status, 404, "no entity at all");
eqJson(r.calls.length, 0, "and nothing is read for it");

r = await post("delete", { entity: "Order", id: "o1" });
eqJson([r.status, r.json.error?.code, r.calls.length], [404, "UNKNOWN_OP", 0], "a write is not a read: there is no such op");

r = await post("list", "not json");
eqJson(r.status, 400, "a body that is not JSON");
r = await post("list", "[1,2]");
eqJson(r.status, 400, "a body that is not an object");

const me: Response = await route.GET(new Request("http://app/api/read/me"), { params: Promise.resolve({ op: "me" }) });
const meBody: any = await me.json();
eqJson([me.status, meBody.user?.role, meBody.account?.id], [200, "Admin", "u1"], "GET me: the person and their own record");
const bad: Response = await route.GET(new Request("http://app/api/read/list"), { params: Promise.resolve({ op: "list" }) });
eqJson(bad.status, 405, "any other read is a POST");

// ── WHO MAY READ WHAT ────────────────────────────────────────────────────────
const admin = { id: "u1", name: "Ann", email: "a@x.io", role: "Admin" };
const member = { id: "u2", name: "Bo", email: "b@x.io", role: "Member" };

sdk.setUser(member);
r = await post("list", { entity: "Order" });
eqJson(r.status, 200, "a signed-in person reads what an authenticated page reads");
r = await post("list", { entity: "Audit" });
eqJson([r.status, r.json.error?.code, r.calls.filter((c: unknown[]) => c[0] === "listPage").length], [403, "FORBIDDEN", 0],
  "an entity only an Admin page reads is a 403 for a Member, and nothing is read");
for (const op of ["record", "records", "count", "total", "series", "query", "similar", "near"]) {
  r = await post(op, { entity: "Audit", id: "a1", ids: ["a1"], fn: "sum", field: "id", groupBy: "id", measures: { n: { fn: "count" } } });
  eqJson(r.status, 403, `${op} on an Admin-only entity is a 403 for a Member`);
}
r = await post("widget", { id: "WID-002" });
eqJson([r.status, r.json.error?.code], [403, "FORBIDDEN"], "a widget on an Admin-only page is a 403 for a Member");
r = await post("widget", { id: "WID-001" });
eqJson(r.status, 200, "a widget on an authenticated page is the Member's");

sdk.setUser(admin);
r = await post("list", { entity: "Audit" });
eqJson(r.status, 200, "the Admin reads it");
r = await post("widget", { id: "WID-002" });
eqJson(r.status, 200, "and its widget");

sdk.setUser(null);
r = await post("list", { entity: "Order" });
eqJson([r.status, r.json.error?.code], [401, "UNAUTHENTICATED"], "nobody signed in: an authenticated page's entity is a 401");
r = await post("list", { entity: "Audit" });
eqJson(r.status, 401, "and an Admin's");
r = await post("list", { entity: "Tool" });
eqJson(r.status, 200, "an entity a PUBLIC page reads is anyone's");
r = await post("widget", { id: "WID-001" });
eqJson(r.status, 401, "a widget on an authenticated page is not anonymous");
sdk.setUser(admin);

// ── A COLUMN THAT IS NOT THE ENTITY'S OWN ────────────────────────────────────
const refused = async (op: string, body: Record<string, unknown>, why: string) => {
  const x = await post(op, { entity: "Order", ...body });
  eqJson([x.status, x.json.error?.code, x.calls.length], [400, "BAD_REQUEST", 0], why);   // and nothing was read
};
await refused("list", { where: { passwordHash: "x" } }, "list: a hidden column cannot be probed by equality");
await refused("list", { sort: "passwordHash" }, "list: or by ordering");
await refused("count", { where: { passwordHash: "x" } }, "count: by equality");
await refused("total", { fn: "sum", field: "passwordHash" }, "total: the summed field");
await refused("total", { fn: "sum", field: "total", where: { secret_encrypted: "x" } }, "total: its filter");
await refused("series", { groupBy: "passwordHash" }, "series: the grouping");
await refused("series", { groupBy: "status", fn: "sum", field: "passwordHash" }, "series: the summed field");
await refused("query", { measures: { n: { fn: "sum", field: "passwordHash" } } }, "query: a measure's field");
await refused("query", { measures: { n: { fn: "count" } }, dimensions: ["passwordHash"] }, "query: a dimension");
await refused("query", { measures: { n: { fn: "count" } }, dimensions: [{ field: "passwordHash", bucket: "day" }] }, "query: a bucketed dimension");
await refused("query", { measures: { n: { fn: "count" } }, where: { passwordHash: "x" } }, "query: its filter");
await refused("query", { measures: { n: { fn: "count" } }, timeField: "passwordHash" }, "query: the time field");
await refused("query", { measures: { n: { fn: "count" } }, sort: { by: "passwordHash" } }, "query: the sort column");
await refused("similar", { field: "passwordHash" }, "similar: the field");
r = await post("near", { entity: "Tool", field: "where", where: { passwordHash: "x" } });
eqJson(r.status, 400, "near: its filter");
r = await post("widget", { id: "WID-001", where: { passwordHash: "x" } });
eqJson([r.status, r.json.error?.code], [400, "BAD_REQUEST"], "a widget's filter");

r = await post("query", { entity: "Order", measures: { revenue: { fn: "sum", field: "total" } }, dimensions: ["status"], sort: { by: "revenue" } });
eqJson(r.status, 200, "a measure's own name may be sorted by");
r = await post("list", { entity: "Order", where: { status: "open" }, sort: "total" });
eqJson(r.status, 200, "and the entity's own columns still read");

done("read route");
