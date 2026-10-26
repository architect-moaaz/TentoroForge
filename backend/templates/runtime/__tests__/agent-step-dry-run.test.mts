/**
 * The build-time dry run and an assistant step: the SHIPPED workflows/dry-run.ts and dry-run-stand-in.ts.
 *
 * The dry run executes nothing, so the answer of an assistant step is a stand-in: a sample envelope made from the
 * step's declared output fields, deterministic, with no model and no tool. The steps after it are resolved against it,
 * so a workflow whose later step reads `{{triage.result.urgency}}` is checked against a real-looking value and not
 * refused; what the sample does not hold (a proposal that does not exist in a sample) is still "supplied by the run".
 *
 * Run: __tests__/run-agent-step-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

// dry-run.ts imports the workflow engine's database helpers; what it needs of them is small and is faked here:
// resolving a `{{path}}` against the variables the dry run seeded, the way the engine's own resolver walks one.
installHarness({
  stubs: {
    "./index": `
      const walk = (root, path) => path.split(/\\.|\\[(\\d+)\\]/).filter((p) => p !== undefined && p !== '').reduce((cur, p) => (cur == null ? undefined : cur[p]), root);
      export const _resolveTable = (t) => (t ? { id: {}, petId: {}, urgency: {}, note: {}, appointmentId: {} } : null);
      export const _buildWhere = () => ({});
      export const _resolveValueMap = (values, ctx) => Object.fromEntries(Object.entries(values ?? {}).map(([k, v]) => {
        const m = typeof v === 'string' && v.match(/^\\{\\{\\s*(.+?)\\s*\\}\\}$/);
        return [k, m ? walk(ctx.variables, m[1]) : v];
      }));
      export const listWorkflows = async () => [];`,
  },
});

const standIn: any = await import("../workflows/dry-run-stand-in.ts");
const dry: any = await import("../workflows/dry-run.ts");

const walk = (root: any, path: string) =>
  path.split(/\.|\[(\d+)\]/).filter((p) => p !== undefined && p !== "").reduce((cur: any, p) => (cur == null ? undefined : cur[p]), root);

console.log("the sample answer, per field type");
{
  const config = { outputFields: [
    { name: "urgency", type: "enum", values: ["routine", "soon", "urgent"] },
    { name: "flag", type: "boolean" },
    { name: "score", type: "number" },
    { name: "tags", type: "array" },
    { name: "slot", type: "object" },
    { name: "reason", type: "string" },
    { name: "emptyChoice", type: "enum", values: [] },
    { name: "untyped" },
  ] };
  const s = standIn.agentStepSample(config);
  eqJson(s.result, { urgency: "routine", flag: false, score: 0, tags: [], slot: {}, reason: "sample", emptyChoice: "", untyped: "sample" }, "a choice is its first value, yes/no false, a number 0, a list [], an object {}, text 'sample'");
  eqJson([s.ok, s.needsHuman, s.confidence, s.proposals, s.actions], [true, false, 1, [], []], "ok, no person needed, confidence 1, nothing proposed or done");
  eqJson(Object.keys(s), ["ok", "needsHuman", "confidence", "summary", "result", "proposals", "actions", "usage"], "the same fields as the real envelope");
  eqJson(s.usage, { turns: 0, inputTokens: 0, outputTokens: 0, ms: 0 }, "and it cost nothing");
  eqJson(standIn.agentStepSample(config), s, "deterministic: the same twice");
  eqJson(standIn.agentStepSample({}).result, {}, "a step with no fields has an empty result (the build gate refuses it long before)");
  eqJson(standIn.agentStepSample(null).result, {}, "and a missing config does not throw");
}

console.log("the sample as the dry run reads it");
{
  const view: any = standIn.agentStepView(standIn.agentStepSample({ outputFields: [{ name: "urgency", type: "enum", values: ["soon"] }] }));
  ok(walk({ triage: view }, "triage.result.urgency") === "soon", "what the sample has reads as it is");
  ok(walk({ triage: view }, "triage.needsHuman") === false && walk({ triage: view }, "triage.confidence") === 1, "needsHuman and confidence too");
  ok(String(walk({ triage: view }, "triage.proposals[0].input.petId")) === "dry-run", "a proposal the sample does not have is still supplied by the run, at any depth");
  ok(String(walk({ triage: view }, "triage.result.somethingElse")) === "dry-run", "so is a field it does not know");
  ok(JSON.stringify(view.result) === "{\"urgency\":\"soon\"}", "and it serialises as the plain sample");
  ok(standIn.agentStepView(5) === 5 && standIn.agentStepView(null) === null, "a plain value stays itself");
}

console.log("the nodes that are assistant steps");
{
  const def = { definition: { nodes: [
    { id: "a", type: "action", data: { config: { actionType: "agent_step" } } },
    { id: "b", type: "agent_step", data: { config: {} } },
    { id: "c", type: "action", data: { config: { actionType: "db_insert" } } },
    { id: "", type: "action", data: { config: { actionType: "agent_step" } } },
  ] } };
  eqJson(standIn.agentStepNodes(def).map((n: any) => n.id), ["a", "b"], "by action type or by node type");
  eqJson(standIn.agentStepNodes({}), [], "a definition with no nodes has none");
}

console.log("a workflow with an assistant step is dry-run model-free, and its later steps are checked against the sample");
{
  const def: any = {
    id: "handle", name: "Handle request",
    definition: {
      nodes: [
        { id: "trigger", type: "trigger", data: { config: {} } },
        { id: "triage", type: "action", data: { config: {
          actionType: "agent_step", agentId: "triage", task: "t", outputVar: "triageResult",
          outputFields: [{ name: "urgency", type: "enum", values: ["urgent", "routine"] }, { name: "reason", type: "string" }],
        } } },
        { id: "insert_note", type: "action", data: { config: { actionType: "db_insert", table: "notes", values: {
          urgency: "{{triage.result.urgency}}", note: "{{triage.summary}}", petId: "{{triage.proposals[0].input.petId}}", appointmentId: "{{triageResult.result.reason}}",
        } } } },
      ],
      edges: [],
    },
  };
  const r = dry.dryRunWorkflow(def, {});
  eqJson(r.problems, [], "every value read from the step resolves: no problem is reported");
  ok(r.ok && r.checked === 1, "the workflow is fine and its one database step was checked");

  // a field the later step names is real: the sample's own value reaches it
  const seen: any[] = [];
  const probe: any = JSON.parse(JSON.stringify(def));
  probe.definition.nodes[2].data.config.values = { urgency: "{{triage.result.urgency}}", note: "{{triage.result.reason}}" };
  const r2 = dry.dryRunWorkflow(probe, {});
  seen.push(r2.problems);
  eqJson(seen, [[]], "a later step that reads the step's declared fields is not refused");

  // and the wiring still catches what it always caught
  const broken: any = JSON.parse(JSON.stringify(def));
  broken.definition.nodes[2].data.config.values = { urgency: "{{nowhere.value}}" };
  const r3 = dry.dryRunWorkflow(broken, {});
  ok(!r3.ok && r3.problems[0].problem.includes("resolve to nothing"), "a reference to something nothing supplies is still reported");
}

done("agent step dry run");
