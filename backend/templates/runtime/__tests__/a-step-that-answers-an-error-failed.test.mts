/**
 * A step whose handler answers `{ error }` failed — in the run AND in the
 * execution log. The run failed, but the log row said "completed" with the
 * error tucked inside its output: RK_Test's Create Child inserted
 * patientId "001", Postgres refused it, and the log the owner and Smith read
 * showed a success (forge-v3, 2026-09-28).
 *
 * Runs the SHIPPED engine.ts.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({ stubs: {
  "../feel-lite": "export const evaluateExpression = () => true;",
  "./types": "export default {};",
} });

const engine: any = await import("../workflows/engine.ts");
const io: any = await import("../workflows/node-io.ts");
const rows: any[] = [];
io.registerExecutionLogger((row: any) => { rows.push(row); });
engine.registerActionHandler("db_insert", async () => ({ error: 'invalid input syntax for type uuid: "001"' }));
engine.registerActionHandler("db_query", async () => ({ id: "p-1", rows: [{ id: "p-1" }], count: 1 }));

const workflow = { id: "create-child", name: "Create Child", definition: {
  trigger: { type: "manual" },
  nodes: [
    { id: "trigger", type: "trigger", data: { label: "Start", config: {} } },
    { id: "find_patient", type: "action", data: { label: "Look up patient", config: { actionType: "db_query" } } },
    { id: "insert_child", type: "action", data: { label: "Create child record", config: { actionType: "db_insert" } } },
    { id: "end", type: "end", data: { label: "Child added", config: {} } },
  ],
  edges: [
    { id: "e1", source: "trigger", target: "find_patient" },
    { id: "e2", source: "find_patient", target: "insert_child" },
    { id: "e3", source: "insert_child", target: "end" },
  ],
} };

let result: any;
try { result = await engine.executeWorkflow(workflow, { name: "Adva" }, { id: "p-1" }); }
catch (err) { result = { status: "failed", thrown: String(err) }; }
await new Promise((r) => setTimeout(r, 10));                          // the log write is fire-and-forget

ok(result.status === "failed", "the run that could not insert failed");
const insert = rows.find((r) => r.nodeId === "insert_child");
const lookup = rows.find((r) => r.nodeId === "find_patient");
ok(!!insert, "the insert step was logged");
eqJson(insert?.status, "failed", "the log row of the step that answered an error says failed");
ok(String(insert?.error).includes('invalid input syntax for type uuid: "001"'), "and carries the error");
eqJson(lookup?.status, "completed", "a step that answered no error is completed");
ok(lookup?.error === undefined, "with no error");
done("a step that answers an error failed");
