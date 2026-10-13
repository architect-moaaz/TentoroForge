/**
 * What a screen asks and is told, without React: the read hooks' stable keys
 * (an inline options object must not refetch in a loop), the bodies they send to
 * /api/read/<op>, how a read that failed is said, and a workflow run read
 * exactly as the web SDK reads it — failed, refused, the sentence shown, where
 * the person goes next.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { fakeApp, offline } from "./_fake-app.mts";

installHarness();
const { CookieJar } = await import("../src/sdk/cookies.ts");
const { createClient } = await import("../src/sdk/http.ts");
const { stableKey } = await import("../src/sdk/keys.ts");
const reads = await import("../src/sdk/reads.ts");
const run = await import("../src/sdk/run.ts");
const { channel } = await import("../src/sdk/events.ts");

const client = (app: { fetch: any }) => createClient({ baseUrl: "http://app.test", fetch: app.fetch, jar: new CookieJar([{ name: "forge-test.session-token", value: "ok", path: "/", secure: false, expires: null }]) });

console.log("stable keys");
eqJson(stableKey({ b: 1, a: { d: 2, c: 3 } }) === stableKey({ a: { c: 3, d: 2 }, b: 1 }), true, "the same content in another key order is the same key");
eqJson(stableKey({ a: 1, b: undefined }) === stableKey({ a: 1 }), true, "undefined is left out, as JSON does");
eqJson(stableKey({ where: { status: "open" } }) === stableKey({ where: { status: "done" } }), false, "different content is a different key");
eqJson(stableKey([1, 2]) === stableKey([2, 1]), false, "list order matters");
eqJson(stableKey({ from: new Date("2026-03-01T00:00:00Z") }), '{"from":"2026-03-01T00:00:00.000Z"}', "a Date is its ISO string");
eqJson(stableKey(undefined), "undefined", "undefined has a key (a read with nothing to ask)");
// What the hook does with it, in miniature: an options literal made fresh on every render.
{
  const renders = Array.from({ length: 5 }, () => ({ entity: "Order", options: { where: { status: "open" }, sort: "total" } }));
  eqJson(new Set(renders.map(stableKey)).size, 1, "five renders with a fresh options object give one key — one fetch, not five");
}

console.log("request bodies");
eqJson(reads.requests.list("Task" as never, { where: { status: "open" } as never, limit: 20, page: 2 }), { entity: "Task", where: { status: "open" }, limit: 20, page: 2 }, "list = entity + the web's options");
eqJson(reads.requests.record("Task" as never, "t1"), { entity: "Task", id: "t1" }, "record");
eqJson(reads.requests.total("Task" as never, "sum", "amount" as never), { entity: "Task", fn: "sum", field: "amount", where: undefined }, "total");
eqJson(reads.requests.widget({ id: "WID-001" } as never, { range: { from: "2026-01-01" } }), { id: "WID-001", range: { from: "2026-01-01" } }, "widget is asked by id");

console.log("a read that works, and ones that do not");
{
  const app = fakeApp();
  const c = client(app);
  const page = await reads.read<{ rows: { id: string }[]; total: number }>(c, "list", { entity: "Task" });
  eqJson([page.rows[0].id, page.total], ["o1", 1], "list answers rows and total");
  eqJson(JSON.parse(app.seen[0].body), { entity: "Task" }, "the body is the request");
  eqJson(app.seen[0].path, "/api/read/list", "…to /api/read/list");

  let err: any;
  try { await reads.read(c, "record", { entity: "Task", id: "gone" }); } catch (e) { err = e; }
  ok(err instanceof reads.ReadError && err.status === 404 && err.message === "Not found.", "a record that is not there: a ReadError, status 404, the app's sentence");

  err = undefined;
  try { await reads.read(createClient({ baseUrl: "http://app.test", fetch: app.fetch, jar: new CookieJar() }), "list", { entity: "Task" }); } catch (e) { err = e; }
  ok(err?.status === 401 && /Not authenticated/.test(err.message), "signed out: status 401 and the middleware's own sentence");

  err = undefined;
  try { await reads.read(client({ fetch: offline }), "count", { entity: "Task" }); } catch (e) { err = e; }
  ok(err?.status === 0 && /could not be reached/.test(err.message), "no network: status 0 and a sentence");
}

console.log("a workflow run, read as the web reads it");
{
  const app = fakeApp();
  const c = client(app);
  let out = await run.runWorkflowRequest(c, "WF-OK", { title: "x" });
  ok(out.ok && out.error === null && out.result.id === "r1" && (out.result.reply as any).total === 5, "ok: the receipt carries id, records and reply");
  eqJson(JSON.parse(app.seen[0].body), { input: { title: "x" } }, "the body is { input }");
  eqJson(app.seen[0].path, "/api/workflows/WF-OK/execute", "…to the workflow's execute route");

  out = await run.runWorkflowRequest(c, "WF-REFUSE", {});
  ok(!out.ok && out.refused && out.error === "A refund over 500 needs a manager.", "refused: the rules' own sentence, and refused is true");

  out = await run.runWorkflowRequest(c, "WF-BOOM", {});
  ok(!out.ok && !out.refused && out.error === "The step failed.", "a broken step: failed, not refused, with the message from { error: { message } }");

  out = await run.runWorkflowRequest(c, "WF-FAILED200", {});
  ok(!out.ok && out.error === "Something went wrong (200).", "status 'failed' in a 200 is still a failed run");

  out = await run.runWorkflowRequest(c, "WF-NOERR", {});
  ok(!out.ok && out.error === "Something went wrong (502).", "an answer that is not JSON still says what it can");

  out = await run.runWorkflowRequest(c, "WF/ODD id", {});
  ok(app.seen[app.seen.length - 1].path === "/api/workflows/WF%2FODD%20id/execute", "a workflow id is URL-encoded");

  out = await run.runWorkflowRequest(client({ fetch: offline }), "WF-OK", {});
  ok(!out.ok && /could not be reached/.test(out.error ?? ""), "no network: ok false and a sentence, never a throw");
}

console.log("humanError and readRun");
eqJson(run.humanError({ error: "plain" }, 400), "plain", "a string error");
eqJson(run.humanError({ error: { message: "nested" } }, 400), "nested", "an error object's message");
eqJson(run.humanError({}, 503), "Something went wrong (503).", "nothing said: the status");
eqJson(run.readRun(200, true, { status: "completed" }), { failed: false, refused: false, message: null }, "a completed run");
eqJson(run.readRun(422, false, { status: "failed", refused: true, error: "No." }).refused, true, "refused only when it also failed");
eqJson(run.readRun(200, true, { refused: true }).refused, false, "a stray refused flag on a success is not a refusal");

console.log("where a finished run sends the person");
eqJson(run.nextStop({}, "/orders"), { kind: "route", to: "/orders" }, "the screen's redirectTo");
eqJson(run.nextStop({ redirect: "/orders/9" }, "/orders"), { kind: "route", to: "/orders/9" }, "the run's own redirect wins");
eqJson(run.nextStop({ redirect: "https://pay.example/c" }, "/orders"), { kind: "external", to: "https://pay.example/c" }, "an outside address is for the browser");
eqJson(run.nextStop({}, undefined), null, "nowhere: stay and show fresh data");

console.log("events");
{
  const ch = channel<number>();
  const got: number[] = [];
  const off = ch.subscribe((n) => got.push(n));
  ch.emit(1); off(); ch.emit(2);
  eqJson(got, [1], "a listener hears events until it unsubscribes");
  const quiet = channel<number>();
  quiet.subscribe(() => { throw new Error("bad listener"); });
  quiet.subscribe((n) => got.push(n * 10));
  const warn = console.warn; console.warn = () => {};
  quiet.emit(7);
  console.warn = warn;
  eqJson(got, [1, 70], "a listener that throws does not stop the next one");
}

done("read and run");
