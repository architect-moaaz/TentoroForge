// A business rule is in force wherever its record is written.
//
// Found on a task board Kimi built (2026-10-14): "a task must have a title"
// and "new tasks default to todo" were in the app's rules file and did
// nothing. The default scope was `form`, the server skipped every `form` rule
// and the form route threw their errors and values away; the data API named
// the record by its URL ("tasks") and the engine matched only "Task"; a blank
// title was dropped before the rules ran, so `title = ""` never matched; and
// the rules were read once for the life of the server, so a rule changed in
// the Business Rules tab needed a restart nobody made.
import assert from "node:assert/strict";
import {
  setRules, evaluateRuleSet, evaluateFormRules, evaluateRuleSetForTable,
  effectiveScope, normalizeBlankChecks, ruleGoverns,
} from "../rules/engine.ts";

const ca = (id: string, model: string, whenFeel: string, then: any[], extra: any = {}) => ({
  id, name: id, rule_type: "condition_action", model_name: model, is_active: true,
  config: { source: "blueprint", whenFeel, then, otherwise: [], salience: 0, ...extra },
});

// ── where a rule runs: by what it does ──────────────────────────────────────
assert.equal(effectiveScope({ scope: "form", then: [{ type: "show_error", message: "x" }] } as any), "entity",
  "a form rule that refuses a save is the record's rule");
assert.equal(effectiveScope({ scope: "form", then: [{ type: "set_default", field: "s" }] } as any), "entity",
  "a form rule that sets a value runs on save too");
assert.equal(effectiveScope({ scope: "form", then: [{ type: "set_visibility", field: "s" }] } as any), "form",
  "a rule about how the form looks stays on the form");
assert.equal(effectiveScope({ scope: "server", then: [{ type: "show_error" }] } as any), "server");
assert.equal(effectiveScope({ then: [] } as any), "entity");
console.log("effective scope: PASS ✅");

// ── names: the entity, its table, its URL ───────────────────────────────────
assert.ok(ruleGoverns("Task", "tasks") && ruleGoverns("Task", "Task") && ruleGoverns("Category", "categories"));
assert.ok(!ruleGoverns("Task", "Taskboard") && !ruleGoverns(null, "tasks"));
console.log("name matching: PASS ✅");

// ── blank means blank, however it arrives ───────────────────────────────────
assert.equal(normalizeBlankChecks('title = ""'), '(title = null or title = "")');
assert.equal(normalizeBlankChecks("title = null"), '(title = null or title = "")');
assert.equal(normalizeBlankChecks('title != ""'), '(title != null and title != "")');
assert.equal(normalizeBlankChecks('status = "done" and note = ""'), 'status = "done" and (note = null or note = "")');
assert.equal(normalizeBlankChecks('note = "a = \\"\\""'), 'note = "a = \\"\\""', "text inside quotes is untouched");
assert.equal(normalizeBlankChecks("amount >= 10"), "amount >= 10");
assert.equal(normalizeBlankChecks("previous.status = null"), '(previous.status = null or previous.status = "")');
console.log("blank checks: PASS ✅");

// ── the task board's two rules, exactly as the build wrote them ─────────────
setRules([
  ca("RULE-004", "Task", 'status = null or status = ""',
     [{ id: "a", field: "status", type: "set_default", value: "todo", valueMode: "literal" }], { scope: "form" }),
  ca("RULE-005", "Task", 'title = ""',
     [{ id: "b", field: "title", type: "show_error", message: "A task must have a title." }], { scope: "form" }),
]);
// The data API passes the URL segment and drops blank values.
const viaApi = await evaluateRuleSet("tasks", "create", { dueDate: "2026-10-20" });
assert.deepEqual(viaApi.errors, ["A task must have a title."], "a blank title is refused through /api/data/tasks");
assert.equal(viaApi.patches.status, "todo", "status defaults to todo on save");
const okTask = await evaluateRuleSet("tasks", "create", { title: "Write plan" });
assert.deepEqual(okTask.errors, [], "a titled task is accepted");
// The form, while typing: the blank title arrives as "".
const typing = await evaluateFormRules("Task", { title: "" });
assert.deepEqual(typing.errors, ["A task must have a title."], "the form says it before the save");
// The workflow path, by table name.
const viaWorkflow = await evaluateRuleSetForTable("tasks", "create", { title: "" });
assert.deepEqual(viaWorkflow.errors, ["A task must have a title."], "the workflow path refuses it too");
console.log("task board rules enforced: PASS ✅");

// ── a rule about a change reads the record as it was ────────────────────────
setRules([
  ca("RULE-010", "Task", 'previous.status = "done" and status = "todo"',
     [{ id: "c", type: "show_error", message: "A done task cannot go back to todo." }], { scope: "entity" }),
]);
const back = await evaluateRuleSet("Task", "update", { status: "todo" }, undefined, { status: "done" });
assert.deepEqual(back.errors, ["A done task cannot go back to todo."]);
const forward = await evaluateRuleSet("Task", "update", { status: "done" }, undefined, { status: "doing" });
assert.deepEqual(forward.errors, []);
const created = await evaluateRuleSet("Task", "create", { status: "todo" });
assert.deepEqual(created.errors, [], "a new record has no previous value");
console.log("previous values: PASS ✅");

// ── required is enforced on save, not only drawn ────────────────────────────
setRules([
  ca("RULE-020", "Expense", "amount > 5000",
     [{ id: "d", type: "set_required", field: "managerNote", required: true }], { scope: "entity" }),
]);
const noNote = await evaluateRuleSet("expenses", "create", { amount: 9000 });
assert.deepEqual(noNote.errors, ["Manager note is required."]);
const withNote = await evaluateRuleSet("expenses", "create", { amount: 9000, managerNote: "client dinner" });
assert.deepEqual(withNote.errors, []);
const small = await evaluateRuleSet("expenses", "create", { amount: 100 });
assert.deepEqual(small.errors, []);
assert.ok(small.formHints.length === 0 || !small.formHints.some((h) => h.required), "no requirement below the limit");
console.log("required on save: PASS ✅");

// ── a length limit: "a title is at most 60 characters" ──────────────────────
setRules([
  ca("RULE-025", "Task", "string length(title) > 60",
     [{ id: "g", field: "title", type: "show_error", message: "Keep the title to 60 characters." }], { scope: "entity" }),
]);
assert.deepEqual((await evaluateRuleSet("tasks", "create", { title: "x".repeat(61) })).errors,
                 ["Keep the title to 60 characters."]);
assert.deepEqual((await evaluateRuleSet("tasks", "create", { title: "x".repeat(60) })).errors, []);
assert.deepEqual((await evaluateRuleSet("tasks", "create", {})).errors, [], "no title is not a long title");
console.log("length limit: PASS ✅");

// ── side effects are handed to the write path ───────────────────────────────
setRules([
  ca("RULE-030", "Order", "total > 50000",
     [{ id: "e", type: "trigger_workflow", workflow: "FLOW-004" },
      { id: "f", type: "send_notification", message: "A large order needs approval." }], { scope: "form" }),
]);
const big = await evaluateRuleSet("orders", "create", { total: 60000 });
assert.deepEqual(big.sideEffects, [
  { type: "trigger_workflow", workflow: "FLOW-004" },
  { type: "send_notification", message: "A large order needs approval." },
], "a form-scope rule with effects still starts them on save");
console.log("side effects: PASS ✅");

console.log("rules-are-enforced: ALL ASSERTIONS PASS ✅");
