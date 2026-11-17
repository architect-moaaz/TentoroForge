/**
 * A decision table's output is what its cell says, and a field holds one value.
 *
 * The #29 review (2026-11-13) ran the merged one-evaluator decision tables and
 * found three ways an answer came out as something else:
 *   - an output cell was worked out as arithmetic: `2026-01-01` became 2024,
 *     `Tier-1` became -1, `N/A` became null;
 *   - an input bound to a variable the run did not carry matched nothing,
 *     where the workflow step used to read the column's own name;
 *   - Collect and Rule order wrote a list (["high","mid"]) over a record's
 *     text field on a save.
 *
 * Runs the SHIPPED rules/decision-table.ts, rules/engine.ts and
 * workflows/decision.ts.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();
const { outputValue, evaluateTable } = await import("../rules/decision-table.ts");
const { setRules, evaluateRuleSet } = await import("../rules/engine.ts");
const { evaluateDecision } = await import("../workflows/decision.ts");

// ---- output cells ------------------------------------------------------- //
for (const cell of ["2026-01-01", "2026-01-01T09:00:00Z", "1-3", "01/02/2026", "Tier-1", "Level-2", "N/A", "Yes/No"]) {
  eqJson(outputValue(cell, { amount: 10 }), cell, `${cell} is that text`);
}
eqJson(outputValue("amount * 0.1", { amount: 500 }), 50, "a formula on a field is worked out");
eqJson(outputValue("amount - 5", { amount: 500 }), 495, "spaced arithmetic on a field is worked out");
eqJson(outputValue("amount/4", { amount: 500 }), 125, "a slash over a field the record has is division");
ok(typeof outputValue("discount * 2", {}) !== "string", "a formula on an absent number is still not text");

// ---- inputs read their binding, then their name ------------------------- //
const big = (binding?: string) => ({
  hitPolicy: "F", inputs: [{ name: "amount", ...(binding ? { variableBinding: binding } : {}) }],
  outputs: [{ name: "o" }], rules: [{ inputEntries: ["> 5"], outputEntries: ["big"] }],
});
eqJson(evaluateTable(big("expense.amount"), { amount: 10 }).outputs, { o: "big" }, "binding absent: the column's name");
eqJson(evaluateTable(big("expense.amount"), { expense: { amount: 10 } }).outputs, { o: "big" }, "a dotted binding reads the path");
eqJson(evaluateTable(big("total"), { total: 1, amount: 10 }).outputs, {}, "a binding that is there wins over the name");
const wf = { variables: { amount: 10 } as Record<string, unknown> };
evaluateDecision({ decisionTable: big("expense.amount") as any }, wf);
eqJson(wf.variables.o, "big", "the workflow step reads the name when the binding is not in the run");

// ---- a field holds one value ------------------------------------------- //
const tiers = (hp: string) => ({
  id: "R" + hp, name: "tier", rule_type: "decision_table", model_name: "Expense", is_active: true,
  config: { table: { hitPolicy: hp, inputs: [{ name: "amount" }], outputs: [{ name: "tier" }],
    rules: [{ inputEntries: ["> 100"], outputEntries: ["high"] }, { inputEntries: ["> 10"], outputEntries: ["mid"] }] } },
});
for (const hp of ["C", "COLLECT", "R"]) {
  setRules([tiers(hp) as any]);
  const r = await evaluateRuleSet("Expense", "create", { amount: 500 });
  eqJson(r.patches.tier, "high", `${hp}: the record's text field takes the first matched row's value`);
}
setRules([tiers("C") as any]);
let r = await evaluateRuleSet("Expense", "update", { amount: 500, tier: ["old"] });
eqJson(r.patches.tier, ["high", "mid"], "a field that holds a list takes the list");
setRules([tiers("F") as any]);
r = await evaluateRuleSet("Expense", "create", { amount: 500 });
eqJson(r.patches.tier, "high", "First as before");
setRules([{ ...tiers("F"), config: { table: { hitPolicy: "F", inputs: [{ name: "amount" }], outputs: [{ name: "due" }],
  rules: [{ inputEntries: ["-"], outputEntries: ["2026-01-01"] }] } } } as any]);
r = await evaluateRuleSet("Expense", "create", { amount: 5 });
eqJson(r.patches.due, "2026-01-01", "a date cell on a save is that date");

const run = { variables: { expense: { amount: 500 } } as Record<string, unknown> };
evaluateDecision({ rule: "RR" }, run, tiers("R") as any);
eqJson((run.variables.expense as any).tier, "high", "Rule order in a workflow puts one value on the record");
eqJson(run.variables.tier, ["high", "mid"], "and the whole list in the run's variables");

done("decision-output");
