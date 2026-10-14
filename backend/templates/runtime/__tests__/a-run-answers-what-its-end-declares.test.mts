/**
 * An `end` may declare what the page that ran the workflow reads back —
 * `reply`, a few named templates — and where the person goes next,
 * `redirect`. The run's reply is a receipt (its variables never leave the
 * server), so a checkout URL a step produced had no way back to the page
 * until the end named it (2026-10-12). A refused end tells, never redirects.
 *
 * Runs the SHIPPED engine.ts.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({ stubs: {
  "../feel-lite": "export const evaluateExpression = () => true;",
  "./types": "export default {};",
} });

const engine: any = await import("../workflows/engine.ts");
engine.registerActionHandler("db_insert", async () => ({ inserted: true, id: "o-1" }));
engine.registerActionHandler("create_checkout", async () => ({ url: "https://pay.example.test/s/abc", sessionId: "abc" }));

const def = (endConfig: Record<string, unknown>) => ({ id: "place-order", name: "Place order", definition: {
  trigger: { type: "manual" },
  nodes: [
    { id: "trigger", type: "trigger", data: { label: "Start", config: {} } },
    { id: "insert_order", type: "action", data: { label: "Save the order", config: { actionType: "db_insert" } } },
    { id: "checkout", type: "action", data: { label: "Open checkout", config: { actionType: "create_checkout" } } },
    { id: "end", type: "end", data: { label: "Sent to pay", config: endConfig } },
  ],
  edges: [
    { id: "e1", source: "trigger", target: "insert_order" },
    { id: "e2", source: "insert_order", target: "checkout" },
    { id: "e3", source: "checkout", target: "end" },
  ],
} });

{
  const result = await engine.executeWorkflow(def({ refused: false, reply: { order: "{{insert_order.id}}", session: "{{checkout.sessionId}}" },
                                                     redirect: "{{checkout.url}}" }), {}, { id: "u-1" });
  eqJson(result.status, "completed", "the run completed");
  eqJson(result.reply, { order: "o-1", session: "abc" }, "the end's reply is filled from the steps, by name");
  eqJson(result.redirect, "https://pay.example.test/s/abc", "the end's redirect is the address a step produced");
}
{
  const result = await engine.executeWorkflow(def({ refused: false, redirect: "/orders/{{insert_order.id}}" }), {}, { id: "u-1" });
  eqJson(result.redirect, "/orders/o-1", "a route of the application is filled the same way");
  ok(result.reply === undefined, "no reply was declared, so none is answered");
}
{
  const result = await engine.executeWorkflow(def({ refused: true, message: "Out of stock", redirect: "/orders/{{insert_order.id}}" }), {}, { id: "u-1" });
  eqJson(result.status, "failed", "a refused end fails the run");
  ok(result.redirect === undefined, "and sends the person nowhere");
}
{
  const result = await engine.executeWorkflow(def({}), {}, { id: "u-1" });
  ok(result.reply === undefined && result.redirect === undefined, "an end that declares nothing answers nothing");
}
done("a run answers what its end declares");
