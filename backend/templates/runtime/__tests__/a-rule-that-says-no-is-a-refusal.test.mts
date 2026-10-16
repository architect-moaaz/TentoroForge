/**
 * A business rule that refuses a workflow's save is a REFUSAL, said in the
 * rule's own words. It was a crash: "Change status failed" with "Save the new
 * status: A task in progress needs a due date." as small print (Task Board,
 * 2026-10-14) — the toast a person reads names the step, not the reason.
 * Any other step error is still a failure, prefixed with its step.
 *
 * Runs the SHIPPED engine.ts.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({ stubs: {
  "../feel-lite": "export const evaluateExpression = () => true;",
  "./types": "export default {};",
} });

const engine: any = await import("../workflows/engine.ts");
engine.registerActionHandler("db_update", async () => ({
  error: "A task in progress needs a due date.", refusedByRule: true }));
engine.registerActionHandler("db_insert", async () => ({ error: "relation \"tasks\" does not exist" }));

const flow = (actionType: string) => ({ id: "change-status", name: "Change status", definition: {
  trigger: { type: "manual" },
  nodes: [
    { id: "trigger", type: "trigger", data: { label: "Start", config: {} } },
    { id: "save", type: "action", data: { label: "Save the new status", config: { actionType } } },
    { id: "end", type: "end", data: { label: "Done", config: {} } },
  ],
  edges: [
    { id: "e1", source: "trigger", target: "save" },
    { id: "e2", source: "save", target: "end" },
  ],
} });

const refused = await engine.executeWorkflow(flow("db_update"), { status: "doing" }, { id: "u-1" });
eqJson(refused.status, "failed", "a refused save did not happen");
eqJson(refused.refused, true, "and it is a refusal, not a crash");
eqJson(refused.error, "A task in progress needs a due date.", "said in the rule's own words");

const broke = await engine.executeWorkflow(flow("db_insert"), { status: "doing" }, { id: "u-1" });
eqJson(broke.status, "failed", "a step that broke failed");
ok(broke.refused !== true, "and is not a refusal");
ok(String(broke.error).startsWith("Save the new status: "), "its error names the step");
done("a rule that says no is a refusal");
