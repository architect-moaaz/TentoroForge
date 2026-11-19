/**
 * An event is processed before the host stops the process.
 *
 * The bus processes an event right after writing it, without holding up the
 * write. On Vercel the function is frozen once the reply is sent, so that work
 * never ran: on DITANS Test (wzml1sa6, 2026-11-19) a move wrote
 * `applications.updated` and nothing it should have started ran until the next
 * cron sweep. The processing is now handed to the host's own "keep running
 * until this is done" — Vercel's request context, else Next's `after()`.
 *
 * Runs the SHIPPED events/bus.ts and events/keep-alive.ts over a stub
 * database holding forge_events in memory.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const g = globalThis as any;
g.__EVENTS = [] as any[];
g.__STARTED = [] as string[];
g.__AFTER = [] as Array<() => unknown>;
g.__AFTER_ON = false;

installHarness({
  stubs: {
    "drizzle-orm": `export const sql = (strings, ...values) => ({ text: strings.join("?"), values });`,
    "@/db": `
      export const db = {
        async execute(q) {
          const text = q.text || "";
          if (text.includes("INSERT INTO forge_events")) {
            const [type, entity, entity_id, payload] = q.values;
            const id = "evt-" + (globalThis.__EVENTS.length + 1);
            globalThis.__EVENTS.push({ id, type, entity, entity_id, payload: JSON.parse(payload), processed: false });
            return [{ id }];
          }
          if (text.includes("UPDATE forge_events SET processed_at")) {
            const claimed = globalThis.__EVENTS.filter((e) => !e.processed).slice(0, q.values[0]);
            for (const e of claimed) e.processed = true;
            return claimed.map(({ id, type, entity, entity_id, payload }) => ({ id, type, entity, entity_id, payload }));
          }
          return [];
        },
      };`,
    "@/lib/workflows": `
      export async function listWorkflows() {
        return [{ id: "record-application-stage-event", trigger: { kind: "event", event: "applications.updated" } }];
      }
      export async function triggerWorkflow(id) { globalThis.__STARTED.push(id); return { status: "completed" }; }`,
    // Next's after(): present only when a test says so.
    "next/server": `
      export const after = (fn) => {
        if (!globalThis.__AFTER_ON) throw new Error("after() was called outside a request scope");
        globalThis.__AFTER.push(fn);
      };`,
  },
});

const bus: any = await import("../events/bus.ts");
const keep: any = await import("../events/keep-alive.ts");
const CTX = Symbol.for("@vercel/request-context");
const settle = () => new Promise((r) => setTimeout(r, 30));

console.log("on Vercel, the host is asked to wait for the processing");
const held: Promise<unknown>[] = [];
g[CTX] = { get: () => ({ waitUntil: (p: Promise<unknown>) => held.push(p) }) };
const row = await bus.emitEventAndProcess("applications.updated", { entity: "applications", entityId: "a1", payload: { entity: { id: "a1" } } });
eqJson(row, { id: "evt-1" }, "the event is written");
eqJson(held.length, 1, "its processing is handed to waitUntil");
await held[0];
eqJson(g.__STARTED, ["record-application-stage-event"], "and the process waiting on it has run once waitUntil's work is done");
ok(g.__EVENTS[0].processed, "the event is marked processed");
delete g[CTX];

console.log("under next start or next dev, Next's after() takes it");
g.__AFTER_ON = true;
g.__STARTED = [];
await bus.emitEventAndProcess("applications.updated", { entity: "applications", entityId: "a2", payload: { entity: { id: "a2" } } });
eqJson(g.__AFTER.length, 1, "after() is given the work");
await g.__AFTER[0]();
eqJson(g.__STARTED, ["record-application-stage-event"], "and the process ran");
g.__AFTER_ON = false;

console.log("outside a request (a cron tick, a script), it runs as before");
g.__STARTED = [];
eqJson(await keep.keepRunning(Promise.resolve()), false, "nothing to hand it to: false, and no throw");
await bus.emitEventAndProcess("applications.updated", { entity: "applications", entityId: "a3", payload: { entity: { id: "a3" } } });
await settle();
eqJson(g.__STARTED, ["record-application-stage-event"], "the process still runs");

console.log("a host that throws is not the write's problem");
g[CTX] = { get: () => { throw new Error("no context"); } };
const r4 = await bus.emitEventAndProcess("applications.updated", { entity: "applications", entityId: "a4", payload: {} });
eqJson(r4, { id: "evt-4" }, "the event is still written");
delete g[CTX];

done("an event is processed before the host stops");
