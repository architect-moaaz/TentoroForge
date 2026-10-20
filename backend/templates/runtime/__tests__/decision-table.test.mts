// The one decision-table implementation: cells, hit policies, analysis.
// Run: run-decision-table-tests.sh (bundles with esbuild, then node).
import assert from "node:assert/strict";
import {
  parseCell, matchConstraint, evaluateTable, analyzeTable, normalizeHitPolicy, outputValue,
} from "../rules/decision-table.ts";
import { setRules, evaluateRuleSet, evaluateFormRules } from "../rules/engine.ts";

const m = (cell: string, value: unknown, ctx: Record<string, unknown> = {}) => {
  const p = parseCell(cell);
  assert.ok(p.ok, `cell ${JSON.stringify(cell)} should parse: ${p.error}`);
  return matchConstraint(p.constraint!, value, ctx);
};
let n = 0;
const t = (name: string, fn: () => void) => { fn(); n++; console.log("ok -", name); };

t("anything", () => {
  for (const c of ["", "-", "*", "any", "  "]) assert.equal(m(c, "whatever"), true);
  assert.equal(m("-", null), true);
});

t("text, bare or quoted, exact", () => {
  assert.equal(m("travel", "travel"), true);
  assert.equal(m('"travel"', "travel"), true);
  assert.equal(m("travel", "Travel"), false);
  assert.equal(m("office supplies", "office supplies"), true);
  assert.equal(m('"a, b"', "a, b"), true, "a comma inside quotes is text");
});

t("either of, comma separated", () => {
  assert.equal(m("travel, meals", "meals"), true);
  assert.equal(m("travel, meals", "office"), false);
});

t("numbers compare as numbers, whether the record holds 5000 or '5000'", () => {
  assert.equal(m("5000", 5000), true);
  assert.equal(m("5000", "5000"), true);
  assert.equal(m("5000", "5000.0"), true);
  assert.equal(m("5000", 5001), false);
});

t("comparisons", () => {
  assert.equal(m("> 5000", 5000.01), true);
  assert.equal(m("> 5000", 5000), false);
  assert.equal(m(">= 5000", 5000), true);
  assert.equal(m("< 0", -1), true);
  assert.equal(m("<= 10", 10), true);
  assert.equal(m("> 5000", null), false, "nothing is not more than 5000");
  assert.equal(m("> 5000", "abc"), false);
  assert.equal(m("!= travel", "meals"), true);
  assert.equal(m("<> travel", "travel"), false);
});

t("ranges include or exclude their ends", () => {
  assert.equal(m("[1..10]", 1), true);
  assert.equal(m("[1..10]", 10), true);
  assert.equal(m("(1..10]", 1), false);
  assert.equal(m("[1..10)", 10), false);
  assert.equal(m("]1..10[", 5), true);
  assert.equal(m("]1..10[", 1), false);
  assert.equal(m("[1..10]", "7"), true);
  assert.equal(m("[0.5..1.5]", 1.25), true);
});

t("date ranges and date comparisons", () => {
  assert.equal(m('["2026-01-01".."2026-03-31"]', "2026-02-15"), true);
  assert.equal(m('["2026-01-01".."2026-03-31"]', "2026-04-01"), false);
  assert.equal(m('> "2026-06-30"', "2026-07-01T10:00:00Z"), true);
  assert.equal(m('>= date("2026-01-01")', "2025-12-31"), false);
});

t("not(…)", () => {
  assert.equal(m("not(travel, meals)", "office"), true);
  assert.equal(m("not(travel, meals)", "meals"), false);
  assert.equal(m("not([1..10])", 11), true);
});

t("compared with another field of the record", () => {
  assert.equal(m("> budget", 120, { budget: 100 }), true);
  assert.equal(m("> budget", 80, { budget: 100 }), false);
  assert.equal(m("<= budget", 100, { budget: "100" }), true);
});

t("nothing and yes/no", () => {
  assert.equal(m("null", null), true);
  assert.equal(m("null", ""), true);
  assert.equal(m("null", "x"), false);
  assert.equal(m("true", true), true);
  assert.equal(m("false", "false"), true);
});

t("cells the engine cannot read say why", () => {
  for (const [cell, word] of [
    ["[10..1]", "starts after"], ['"open', "not closed"], ["> ", "needs"], ["[a..b]", "numbers or dates"],
    ["travel,,meals", "empty"], ["[1..\"2026-01-01\"]", "both"], ["not()", "leaves out"], ["not( - )", "leaves out"],
  ] as const) {
    const p = parseCell(cell);
    assert.equal(p.ok, false, cell);
    assert.ok(p.error!.includes(word), `${cell}: ${p.error}`);
  }
});

t("hit policy from a letter or a word", () => {
  assert.equal(normalizeHitPolicy("U"), "U");
  assert.equal(normalizeHitPolicy("unique"), "U");
  assert.equal(normalizeHitPolicy("collect"), "C");
  assert.equal(normalizeHitPolicy("RULE ORDER"), "R");
  assert.equal(normalizeHitPolicy(undefined), "F");
  assert.equal(normalizeHitPolicy("nonsense"), "F");
});

const approval = (hitPolicy: string, extra: Record<string, unknown> = {}) => ({
  hitPolicy, ...extra,
  inputs: [{ name: "amount", type: "number" }, { name: "category", type: "string", values: ["travel", "meals", "office"] }],
  outputs: [{ name: "approver", type: "string", values: ["cfo", "manager", "none"] }],
  rules: [
    { inputEntries: ["> 5000", "-"], outputEntries: ["cfo"] },
    { inputEntries: ["[1000..5000]", "travel"], outputEntries: ["manager"] },
    { inputEntries: ["< 1000", "-"], outputEntries: ["none"] },
  ],
});

t("First: the first matching row", () => {
  const r = evaluateTable(approval("F"), { amount: 6000, category: "travel" });
  assert.deepEqual(r.matched, [0]);
  assert.deepEqual(r.outputs, { approver: "cfo" });
  const r2 = evaluateTable(approval("F"), { amount: 2000, category: "meals" });
  assert.deepEqual(r2.matched, []);
  assert.deepEqual(r2.outputs, {});
});

t("Unique: two matches are reported, the first used", () => {
  const tbl = approval("U");
  (tbl.rules as any).push({ inputEntries: [">= 5000", "-"], outputEntries: ["manager"] });
  const r = evaluateTable(tbl, { amount: 7000, category: "office" });
  assert.deepEqual(r.matched, [0, 3]);
  assert.equal(r.outputs.approver, "cfo");
  assert.ok(r.violation && r.violation.includes("rows 1, 4"));
});

t("Priority: the output value listed first wins, not the row", () => {
  const tbl = {
    hitPolicy: "P",
    inputs: [{ name: "score" }],
    outputs: [{ name: "decision", values: ["reject", "review", "approve"] }],
    rules: [
      { inputEntries: [">= 50"], outputEntries: ["approve"] },
      { inputEntries: ["[60..70]"], outputEntries: ["review"] },
      { inputEntries: ["< 65"], outputEntries: ["reject"] },
    ],
  };
  assert.equal(evaluateTable(tbl, { score: 62 }).outputs.decision, "reject");
  assert.equal(evaluateTable(tbl, { score: 68 }).outputs.decision, "review");
  assert.equal(evaluateTable(tbl, { score: 90 }).outputs.decision, "approve");
});

t("Any: agreeing rows are fine, disagreeing ones reported", () => {
  const tbl = {
    hitPolicy: "A", inputs: [{ name: "x" }], outputs: [{ name: "y" }],
    rules: [{ inputEntries: ["> 1"], outputEntries: ["yes"] }, { inputEntries: ["> 2"], outputEntries: ["yes"] },
            { inputEntries: ["> 3"], outputEntries: ["no"] }],
  };
  assert.equal(evaluateTable(tbl, { x: 3 }).violation, undefined);
  assert.ok(evaluateTable(tbl, { x: 4 }).violation);
});

t("Collect: a list, or aggregated", () => {
  const base = {
    hitPolicy: "C", inputs: [{ name: "region" }], outputs: [{ name: "fee", type: "number" }],
    rules: [{ inputEntries: ["-"], outputEntries: ["10"] }, { inputEntries: ["eu"], outputEntries: ["5"] },
            { inputEntries: ["us"], outputEntries: ["7"] }],
  };
  assert.deepEqual(evaluateTable(base, { region: "eu" }).outputs, { fee: [10, 5] });
  assert.equal(evaluateTable({ ...base, aggregation: "SUM" }, { region: "eu" }).outputs.fee, 15);
  assert.equal(evaluateTable({ ...base, aggregation: "count" }, { region: "eu" }).outputs.fee, 2);
  assert.equal(evaluateTable({ ...base, aggregation: "MIN" }, { region: "us" }).outputs.fee, 7);
  assert.equal(evaluateTable({ ...base, aggregation: "MAX" }, { region: "us" }).outputs.fee, 10);
  assert.equal(evaluateTable({ ...base, aggregation: "SUM" }, { region: "jp" }).outputs.fee, 10);
});

t("Rule order: every match, in order", () => {
  const tbl = { hitPolicy: "R", inputs: [{ name: "x" }], outputs: [{ name: "tag" }],
                rules: [{ inputEntries: ["> 1"], outputEntries: ["big"] }, { inputEntries: ["> 0"], outputEntries: ["positive"] }] };
  assert.deepEqual(evaluateTable(tbl, { x: 5 }).outputs, { tag: ["big", "positive"] });
});

t("output cells: text, numbers, and expressions over the record", () => {
  assert.equal(outputValue("approved", {}), "approved");
  assert.equal(outputValue('"approved"', {}), "approved");
  assert.equal(outputValue("42", {}), 42);
  assert.equal(outputValue("amount * 0.1", { amount: 500 }), 50);
  assert.equal(outputValue("-", {}), undefined);
});

t("variableBinding reads and writes the bound field", () => {
  const tbl = { hitPolicy: "F", inputs: [{ name: "Amount", variableBinding: "amount" }],
                outputs: [{ name: "Tier", variableBinding: "tier" }],
                rules: [{ inputEntries: ["> 10"], outputEntries: ["gold"] }] };
  assert.deepEqual(evaluateTable(tbl, { amount: 11 }).outputs, { tier: "gold" });
});

t("a row with a cell the engine cannot read never matches", () => {
  const tbl = { hitPolicy: "F", inputs: [{ name: "x" }], outputs: [{ name: "y" }],
                rules: [{ inputEntries: ["[9..1]"], outputEntries: ["bad"] }, { inputEntries: ["-"], outputEntries: ["ok"] }] };
  assert.equal(evaluateTable(tbl, { x: 5 }).outputs.y, "ok");
});

// ---- analysis ------------------------------------------------------------ //

const kinds = (f: ReturnType<typeof analyzeTable>) => f.map((x) => `${x.severity}:${x.kind}:${x.row ?? "-"}`);

t("a well-formed Unique table has nothing to say", () => {
  assert.deepEqual(analyzeTable(approval("U")), []);
});

t("Unique: overlapping rows are an error, naming both", () => {
  const tbl = approval("U");
  (tbl.rules as any).push({ inputEntries: ["[4000..6000]", "travel"], outputEntries: ["manager"] });
  const f = analyzeTable(tbl);
  assert.ok(f.some((x) => x.kind === "overlap" && x.message.includes("Rows 1 and 4")), JSON.stringify(f));
  assert.ok(f.some((x) => x.kind === "overlap" && x.message.includes("Rows 2 and 4")));
  assert.ok(f.every((x) => x.severity === "error"));
});

t("Unique: touching ranges overlap only when both ends are included", () => {
  const two = (a: string, b: string) => ({ hitPolicy: "U", inputs: [{ name: "x" }], outputs: [{ name: "y" }],
    rules: [{ inputEntries: [a], outputEntries: ["1"] }, { inputEntries: [b], outputEntries: ["2"] }] });
  assert.equal(analyzeTable(two("[1..5]", "[5..9]")).length, 1);
  assert.equal(analyzeTable(two("[1..5)", "[5..9]")).length, 0);
  assert.equal(analyzeTable(two("< 5", ">= 5")).length, 0);
  assert.equal(analyzeTable(two("travel", "meals")).length, 0);
  assert.equal(analyzeTable(two("travel, meals", "not(travel)")).length, 1);
  assert.equal(analyzeTable(two("> budget", "< 5")).length, 0, "a field comparison is not provably overlapping");
});

t("First: a row covered by one above it is unreachable (a warning)", () => {
  const tbl = { hitPolicy: "F", inputs: [{ name: "x" }, { name: "c" }], outputs: [{ name: "y" }],
    rules: [{ inputEntries: ["> 0", "-"], outputEntries: ["a"] }, { inputEntries: ["[5..9]", "travel"], outputEntries: ["b"] },
            { inputEntries: ["< 0", "-"], outputEntries: ["c"] }] };
  assert.deepEqual(kinds(analyzeTable(tbl)), ["warning:unreachable:2"]);
});

t("typos against a column's values are errors, in and out", () => {
  const tbl = approval("F");
  (tbl.rules as any)[1].inputEntries[1] = "travle";
  (tbl.rules as any)[2].outputEntries[0] = "nobody";
  const f = analyzeTable(tbl);
  assert.ok(f.some((x) => x.kind === "value" && x.message.includes("“travle” is not one of travel, meals, office")));
  assert.ok(f.some((x) => x.kind === "value" && x.message.includes("“nobody”")));
});

t("text in a number column is an error", () => {
  const tbl = approval("F");
  (tbl.rules as any)[0].inputEntries[0] = "lots";
  assert.ok(analyzeTable(tbl).some((x) => x.kind === "value" && x.message.includes("not a number")));
});

t("an empty or half-made table says what is missing", () => {
  const f = analyzeTable({ hitPolicy: "F", inputs: [], outputs: [], rules: [] });
  assert.equal(f.filter((x) => x.kind === "shape").length, 3);
  assert.ok(analyzeTable({ hitPolicy: "C", aggregation: "AVG", inputs: [{ name: "x" }], outputs: [{ name: "y" }],
    rules: [{ inputEntries: ["-"], outputEntries: ["1"] }] }).some((x) => x.message.includes("AVG")));
});

t("cell errors carry the row and column", () => {
  const tbl = approval("F");
  (tbl.rules as any)[2].inputEntries[0] = "[10..1]";
  const f = analyzeTable(tbl).find((x) => x.kind === "cell")!;
  assert.equal(f.row, 3);
  assert.equal(f.column, "amount");
});

// ---- through the engine, as an app runs it ------------------------------- //

const tableRule = (on?: string[]) => ({
  id: "RULE-010", name: "Approver by amount", rule_type: "decision_table", model_name: "Expense",
  field_name: null, is_active: true,
  config: { source: "blueprint", ...(on ? { on } : {}), table: {
    hitPolicy: "U", inputs: [{ name: "amount", type: "number" }], outputs: [{ name: "approver" }],
    rules: [{ inputEntries: ["(5000..100000]"], outputEntries: ["cfo"] },
            { inputEntries: ["[0..5000]"], outputEntries: ["manager"] }] } },
});

await (async () => {
  setRules([tableRule() as any]);
  let r = await evaluateRuleSet("Expense", "create", { amount: 5000 });
  assert.equal(r.patches.approver, "manager");
  r = await evaluateRuleSet("Expense", "create", { amount: 5000.5 });
  assert.equal(r.patches.approver, "cfo");
  r = await evaluateRuleSet("expenses", "update", { amount: "250" });
  assert.equal(r.patches.approver, "manager", "a table governs its records by any plural, and reads numeric text");
  n++; console.log("ok - engine: ranges, plural names, numeric text");

  setRules([tableRule(["update"]) as any]);
  assert.equal((await evaluateRuleSet("Expense", "create", { amount: 10 })).patches.approver, undefined);
  assert.equal((await evaluateRuleSet("Expense", "update", { amount: 10 })).patches.approver, "manager");
  n++; console.log("ok - engine: a table that fires on update is quiet on create");

  const refuseOnUpdate = {
    id: "RULE-011", name: "Closed stays closed", rule_type: "condition_action", model_name: "Expense",
    field_name: null, is_active: true,
    config: { whenFeel: 'previous.status = "closed" and status != "closed"', on: ["update"],
              then: [{ id: "t1", type: "show_error", message: "A closed expense cannot be reopened." }], otherwise: [] },
  };
  setRules([refuseOnUpdate as any]);
  assert.deepEqual((await evaluateRuleSet("Expense", "update", { status: "open" }, null, { status: "closed" })).errors,
                   ["A closed expense cannot be reopened."]);
  assert.deepEqual((await evaluateRuleSet("Expense", "create", { status: "open" }, null, null)).errors, []);
  assert.deepEqual((await evaluateFormRules("Expense", { status: "open" })).errors, [], "a new record's form is a create");
  assert.deepEqual((await evaluateFormRules("Expense", { id: "e1", status: "open" }, null, { status: "closed" })).errors,
                   ["A closed expense cannot be reopened."]);
  n++; console.log("ok - engine: a rule on update reads previous, and the form knows create from edit");

  const overlap = tableRule();
  (overlap.config.table.rules as any).push({ inputEntries: ["> 4000"], outputEntries: ["director"] });
  setRules([overlap as any]);
  const warned: string[] = [];
  const orig = console.warn; console.warn = (m: string) => { warned.push(String(m)); };
  const r2 = await evaluateRuleSet("Expense", "create", { amount: 4500 });
  console.warn = orig;
  assert.equal(r2.patches.approver, "manager");
  assert.deepEqual(r2.errors, [], "a broken Unique table never refuses the person's save");
  assert.ok(warned.some((w) => w.includes("More than one row")));
  n++; console.log("ok - engine: a Unique violation is logged, the save goes on");

  // Values first, judgement last: a refusal sees what a table worked out.
  const needsApprover = {
    id: "RULE-012", name: "An approver is needed", rule_type: "condition_action", model_name: "Expense",
    field_name: null, is_active: true,
    config: { whenFeel: "approver = null", then: [{ type: "show_error", message: "No approver." }], otherwise: [],
              scope: "entity", salience: 10 },
  };
  setRules([needsApprover as any, tableRule() as any]);
  let j = await evaluateRuleSet("Expense", "create", { amount: 300 });
  assert.deepEqual([j.errors, j.patches.approver], [[], "manager"], "the table's approver satisfies the check");
  j = await evaluateRuleSet("Expense", "create", { amount: -5 });
  assert.deepEqual(j.errors, ["No approver."], "no row, no approver: refused");
  const form = await evaluateFormRules("Expense", { amount: 300 });
  assert.deepEqual([form.errors, form.patches.approver], [[], "manager"], "the form shows the table's value and no refusal");
  // A rule that sets a value keeps the answer it acted on.
  const defaultAndHint = {
    id: "RULE-013", name: "Default status", rule_type: "condition_action", model_name: "Expense",
    field_name: null, is_active: true,
    config: { whenFeel: "status = null", then: [{ type: "set_default", field: "status", value: "submitted", valueMode: "literal" },
                                               { type: "show_error", message: "Status was blank." }],
              otherwise: [], scope: "entity", salience: 0 },
  };
  setRules([defaultAndHint as any]);
  j = await evaluateRuleSet("Expense", "create", {});
  assert.deepEqual([j.patches.status, j.errors], ["submitted", ["Status was blank."]]);
  n++; console.log("ok - engine: values first, then tables, then refusals on the final record");
})();

console.log(`\n${n} decision-table tests passed`);
