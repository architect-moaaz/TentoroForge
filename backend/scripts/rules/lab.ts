// The rule lab: the generated app's own rules engine, run for the platform.
//
// stdin, one JSON request; stdout, one JSON answer.
//   {op: "analyze", table}                      -> {findings}
//   {op: "simulate", model, event, record, previous, user, rules, focus}
//                                               -> what the app would do on that save
//
// It is the engine that ships in every app (bundled from templates/runtime),
// so what the editor's "Test it" says is what the app does — there is no
// second evaluator to drift from it.
import { analyzeTable, evaluateTable, parseCell } from "../../templates/runtime/rules/decision-table";
import { setRules, evaluateRuleSet, evaluateFormRules, normalizeBlankChecks, firesOn } from "../../templates/runtime/rules/engine";
import { evaluateExpression } from "../../templates/runtime/feel-lite/index";

type Json = Record<string, any>;

async function simulate(req: Json): Promise<Json> {
  const rules: Json[] = Array.isArray(req.rules) ? req.rules : [];
  const model = String(req.model || "");
  const event = req.event === "update" ? "update" : "create";
  const record: Json = { ...(req.record || {}) };
  const previous: Json | null = event === "update" ? (req.previous || {}) : null;
  setRules(rules as any);
  const saved = await evaluateRuleSet(model, event, record, req.user ?? null, previous);
  const form = await evaluateFormRules(model, event === "update" ? { id: "lab", ...record } : record,
                                       req.user ?? null, previous);
  // A line per rule: did it fire on this event, did its condition hold, which
  // rows of a table matched — so "why" is answered, not only "what".
  const trace = rules.map((r) => {
    const config = r.config || {};
    const fires = firesOn(config, event);
    if (r.rule_type === "decision_table") {
      const t = evaluateTable(config.table || {}, { ...record });
      return { id: r.id, name: r.name, kind: "decision_table", fires, matched: t.matched.map((i) => i + 1),
               used: t.used.map((i) => i + 1), outputs: t.outputs, violation: t.violation ?? null };
    }
    let held: boolean | null = null, error: string | null = null;
    try {
      held = Boolean(evaluateExpression(normalizeBlankChecks(String(config.whenFeel || "true")),
                                        { ...record, user: req.user ?? null, previous: previous ?? {} } as any));
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    return { id: r.id, name: r.name, kind: "condition_action", fires, held, error };
  });
  const refused = saved.errors.length > 0;
  return {
    event,
    refused,
    errors: saved.errors,
    patches: saved.patches,
    sideEffects: saved.sideEffects,
    formHints: form.formHints,
    formErrors: form.errors,
    record: { ...record, ...saved.patches },
    trace,
    focus: req.focus ? trace.find((t) => t.id === req.focus) ?? null : null,
  };
}

// Many questions in one run of node: a workflow condition's value for each
// set of variables (as the workflow engine reads it — truthy is yes), and
// what the rules say about each save. Used to tell whether a workflow's own
// check says exactly what a business rule says (services/rule_links.py).
async function batch(req: Json): Promise<Json> {
  const conditions = (Array.isArray(req.conditions) ? req.conditions : []).map((c: Json) => {
    try {
      return { value: Boolean(evaluateExpression(normalizeBlankChecks(String(c.expression || "false")), (c.vars || {}) as any)) };
    } catch (e) {
      return { error: e instanceof Error ? e.message : String(e) };
    }
  });
  const saves: Json[] = [];
  for (const s of Array.isArray(req.saves) ? req.saves : []) {
    try {
      const r = await simulate({ ...s, op: "simulate" });
      saves.push({ refused: r.refused, errors: r.errors });
    } catch (e) {
      saves.push({ error: e instanceof Error ? e.message : String(e) });
    }
  }
  return { conditions, saves };
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", async () => {
  try {
    const req = JSON.parse(raw || "{}") as Json;
    let out: Json;
    if (req.op === "analyze") out = { findings: analyzeTable(req.table || {}) };
    else if (req.op === "cells") out = { cells: (req.cells || []).map((c: string) => parseCell(c)) };
    else if (req.op === "simulate") out = await simulate(req);
    else if (req.op === "batch") out = await batch(req);
    else out = { error: `unknown op ${req.op}` };
    process.stdout.write(JSON.stringify(out));
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: e instanceof Error ? e.message : String(e) }));
  }
});
