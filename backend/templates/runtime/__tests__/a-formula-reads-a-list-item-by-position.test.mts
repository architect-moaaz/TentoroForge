/**
 * A formula reads one item of a list by position, counted from 0.
 *
 * `{{find_route.output[0].id}}` was read in a template, but the same text as a
 * formula did not parse. DITANS's Submit Job For Approval set `routeId` with
 * the formula `find_route.output[0].id`; the engine kept the formula's own
 * spelling, and the next query failed with "invalid input syntax for type
 * uuid" the second time an organisation submitted a job (2026-11-24).
 *
 * Runs the SHIPPED feel-lite, and the SHIPPED engine's `set_variable`.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({});

const feel: any = await import("../feel-lite/index.ts");
const vars = {
  find_route: { output: [{ id: "6c1d5c0a-0000-4000-8000-000000000001", version: 3 }] },
  find_manager: { output: [] as any[] },
};

eqJson(feel.evaluateExpression("find_route.output[0].id", vars), "6c1d5c0a-0000-4000-8000-000000000001",
  "a list item's field, by position from 0");
eqJson(feel.evaluateExpression("find_route.output[0].version + 1", vars), 4, "used inside arithmetic");
eqJson(feel.evaluateExpression("find_route.output[1]", vars), null, "past the end is nothing");
ok(feel.evaluateExpression("find_route.output[1].id", vars) == null, "a field past the end is nothing");
eqJson(feel.evaluateExpression("find_route.output[1].id = null", vars), true, "and equals null");
eqJson(feel.evaluateExpression("find_manager.output[0].organisationMemberId != null", vars), false,
  "a condition over an empty list is false, not an error");
eqJson(feel.evaluateExpression("count(find_route.output) > 0", vars), true, "a whole list as before");
eqJson(feel.evaluateExpression("find_route.output.id", vars), ["6c1d5c0a-0000-4000-8000-000000000001"],
  "a path over a list is still each item's value");
eqJson(feel.evaluateExpression("x in [1, 2]", { x: 2 }), true, "a list after `in` is still a list");

let refused = "";
try { feel.evaluateExpression("rows[a]", { rows: [1], a: 0 }); } catch (e) { refused = String((e as Error).message); }
ok(refused !== "", "only a whole number fits between the brackets");

const v = feel.validateExpression("find_route.output[0].id");
ok(!(v.issues || []).some((i: any) => i.severity === "error"), "the validator the build check uses accepts it");

done();
