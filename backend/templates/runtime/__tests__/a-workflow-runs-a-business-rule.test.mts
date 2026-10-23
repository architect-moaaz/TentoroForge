/**
 * A workflow step can run a business rule of the app by its id — a decision
 * table computing values for later steps, or a condition rule deciding the
 * path — the same rule that guards the record on every save.
 *
 * Before: the `decision` step ignored any reference to a rule, followed every
 * edge whatever matched (the "refuse" path ran beside the "carry on" one) and
 * read hit policies as words the Blueprint never writes.
 *
 * Runs the SHIPPED engine.ts and rules/engine.ts with the real evaluator.
 */
import { installHarness, eqJson, done } from "./_harness.mts";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
installHarness({ stubs: { "./types": "export default {};" },
                 redirect: { "../feel-lite": join(HERE, "..", "feel-lite", "index.ts") } });

const engine: any = await import("../workflows/engine.ts");
const rules: any = await import("../rules/engine.ts");

rules.setRules([
  { id: "RULE-020", name: "Approver by amount", rule_type: "decision_table", model_name: "Expense", is_active: true,
    config: { source: "blueprint", table: {
      hitPolicy: "U", inputs: [{ name: "amount", type: "number" }], outputs: [{ name: "approver" }],
      rules: [{ inputEntries: ["> 5000"], outputEntries: ["cfo"] },
              { inputEntries: ["[0..5000]"], outputEntries: ["manager"] }] } } },
  { id: "RULE-021", name: "Big expenses need a note", rule_type: "condition_action", model_name: "Expense", is_active: true,
    config: { whenFeel: "amount <= 5000 or managerNote != null",
              then: [], otherwise: [{ id: "o1", type: "show_error", message: "Add a manager note for more than 5000." }] } },
  { id: "RULE-023", name: "No big expense without a note", rule_type: "condition_action", model_name: "Expense", is_active: true,
    config: { whenFeel: "amount > 5000 and managerNote = null",
              then: [{ id: "t1", type: "show_error", message: "Over 5000 needs a manager note." }], otherwise: [] } },
  { id: "RULE-024", name: "Flag large", rule_type: "condition_action", model_name: "Expense", is_active: true,
    config: { whenFeel: "amount > 1000", then: [{ id: "t1", type: "set_field", field: "flagged", valueMode: "literal", value: "true" }],
              otherwise: [] } },
  { id: "RULE-022", name: "Switched off", rule_type: "condition_action", model_name: "Expense", is_active: false,
    config: { whenFeel: "true", then: [], otherwise: [] } },
]);

// A refused end is `failed` with `refused: true` — told apart from a crash.
const outcome = (run: any) => (run.refused ? "refused" : run.status);
const recorded: Array<Record<string, unknown>> = [];
engine.registerActionHandler("db_insert", async (cfg: any, ctx: any) => {
  recorded.push({ approver: ctx.variables.approver, amount: ctx.variables.amount });
  return { id: "x-1" };
});

const flow = (rule: string, withElse = true) => ({ id: "submit", name: "Submit expense", definition: {
  trigger: { type: "manual" },
  nodes: [
    { id: "trigger", type: "trigger", data: { label: "Start", config: {} } },
    { id: "check", type: "decision", data: { label: "Check: rule", config: { rule } } },
    { id: "save", type: "action", data: { label: "Save", config: { actionType: "db_insert" } } },
    { id: "refuse", type: "end", data: { label: "Refused", config: { refused: true, message: "Add a manager note for more than 5000." } } },
    { id: "done", type: "end", data: { label: "Saved", config: {} } },
  ],
  edges: [
    { id: "e1", source: "trigger", target: "check" },
    { id: "e2", source: "check", target: "save", data: { edgeType: "then" } },
    ...(withElse ? [{ id: "e3", source: "check", target: "refuse", sourceHandle: "else", data: { edgeType: "else" } }] : []),
    { id: "e4", source: "save", target: "done" },
  ],
} });

console.log("a condition rule decides the path");
let r: any = await engine.executeWorkflow(flow("RULE-021"), { amount: 9000 }, { id: "u" });
eqJson([outcome(r), recorded.length], ["refused", 0], "9000 without a note: the else-path refuses, nothing saved");
eqJson(String(r.error).includes("manager note"), true, "with the rule's message");
r = await engine.executeWorkflow(flow("RULE-021"), { amount: 9000, managerNote: "client dinner" }, { id: "u" });
eqJson([outcome(r), recorded.length], ["completed", 1], "with a note: the then-path saves");
r = await engine.executeWorkflow(flow("RULE-021"), { amount: 120 }, { id: "u" });
eqJson([outcome(r), recorded.length], ["completed", 2], "a small one saves");

console.log("a rule written the natural way — refuse WHEN — is a gate the same way round");
recorded.length = 0;
r = await engine.executeWorkflow(flow("RULE-023"), { amount: 9000 }, { id: "u" });
eqJson([outcome(r), recorded.length], ["refused", 0], "its condition holds, so it refuses: the else-path");
r = await engine.executeWorkflow(flow("RULE-023"), { amount: 9000, managerNote: "ok" }, { id: "u" });
eqJson([outcome(r), recorded.length], ["completed", 1], "it lets this one through: the then-path");

console.log("a rule that never refuses branches on its condition, and its values reach later steps");
recorded.length = 0;
engine.registerActionHandler("db_insert", async (cfg: any, ctx: any) => {
  recorded.push({ approver: ctx.variables.approver, amount: ctx.variables.amount, flagged: ctx.variables.flagged });
  return { id: "x-1" };
});
r = await engine.executeWorkflow(flow("RULE-024"), { amount: 2000 }, { id: "u" });
eqJson([outcome(r), recorded[0]?.flagged], ["completed", true], "held: then-path, flagged = true for the save");
r = await engine.executeWorkflow(flow("RULE-024"), { amount: 10 }, { id: "u" });
eqJson([outcome(r), recorded.length], ["refused", 1], "did not hold: the else-path");

console.log("a decision table computes values for later steps");
recorded.length = 0;
r = await engine.executeWorkflow(flow("RULE-020"), { amount: 7000 }, { id: "u" });
eqJson([outcome(r), recorded[0]?.approver], ["completed", "cfo"], "7000 -> the cfo, seen by the save step");
r = await engine.executeWorkflow(flow("RULE-020"), { amount: 5000 }, { id: "u" });
eqJson(recorded[1]?.approver, "manager", "5000 -> a manager (the range includes its end)");
r = await engine.executeWorkflow(flow("RULE-020"), { amount: -5 }, { id: "u" });
eqJson([outcome(r), recorded.length], ["refused", 2], "no row for -5: the else-path is taken");

console.log("with no else-path drawn, a step carries on whatever it found");
recorded.length = 0;
r = await engine.executeWorkflow(flow("RULE-020", false), { amount: -5 }, { id: "u" });
eqJson([outcome(r), recorded.length], ["completed", 1], "computes nothing, and the workflow goes on");

console.log("the record carried as one variable (expense.amount) is what the rule reads");
recorded.length = 0;
engine.registerActionHandler("db_insert", async (cfg: any, ctx: any) => {
  const e = ctx.variables.expense as any;
  recorded.push({ approver: ctx.variables.approver, recordApprover: e?.approver, flagged: e?.flagged });
  return { id: "x-1" };
});
r = await engine.executeWorkflow(flow("RULE-023"), { expense: { amount: 9000 } }, { id: "u" });
eqJson([outcome(r), recorded.length], ["refused", 0], "a gate on expense.amount refuses 9000 without a note");
r = await engine.executeWorkflow(flow("RULE-023"), { expense: { amount: 9000, managerNote: "ok" } }, { id: "u" });
eqJson([outcome(r), recorded.length], ["completed", 1], "and lets it through with one");
r = await engine.executeWorkflow(flow("RULE-020"), { expense: { amount: 7000 } }, { id: "u" });
eqJson([recorded[1]?.approver, recorded[1]?.recordApprover], ["cfo", "cfo"], "a table's value is the run's and the record's");
r = await engine.executeWorkflow(flow("RULE-024"), { record: { amount: 2000 } }, { id: "u" });
eqJson([outcome(r)], ["completed"], "`record` is the record too");
eqJson((await import("../workflows/decision.ts") as any).recordIn({ expense_item: { a: 1 } }, "ExpenseItem"), { a: 1 },
       "a two-word record is found by its snake name");

console.log("a rule that is gone never passes as a yes; one switched off does not apply");
recorded.length = 0;
r = await engine.executeWorkflow(flow("RULE-404"), { amount: 1 }, { id: "u" });
eqJson([outcome(r), recorded.length], ["refused", 0], "a missing rule takes the else-path");
const step = (r.log || []).find((l: any) => l.nodeId === "check");
eqJson(String(step?.error || "").includes("RULE-404"), true, "and the log names it");
r = await engine.executeWorkflow(flow("RULE-022"), { amount: 1 }, { id: "u" });
eqJson([outcome(r), recorded.length], ["completed", 1], "a switched-off rule lets the run through");
const off = (r.log || []).find((l: any) => l.nodeId === "check");
eqJson([off?.output?.skipped, Boolean(off?.error)], [true, false], "logged as skipped, not as an error");

done("workflow-runs-a-business-rule");
