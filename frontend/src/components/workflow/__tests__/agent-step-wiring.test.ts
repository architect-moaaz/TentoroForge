/**
 * The agent step is wired in everywhere the AI steps are: palette, node normalising, branching, variables, contracts and
 * the text the editor gives the AI chat. One test file per seam would be a lot of files for a handful of lines each.
 */
import { describe, it, expect } from "vitest";
import { NODE_CATEGORIES, missingConfig, visualFor, catalogNode } from "@/catalog/workflowNodes";
import { normalizeWorkflowNodes } from "../utils/normalize-nodes";
import { isBranchingNode } from "../branching";
import { collectWorkflowVariables } from "../workflowVariables";
import { ACTION_CONTRACTS } from "../actionContracts";
import { ACTION_FIELD_SPECS } from "../actionFieldSpecs";
import { buildWorkflowInstruction } from "@/lib/workflow-instruction-builder";
import type { WorkflowDefinition, WorkflowNodeSerialized } from "@/types/workflow";

const node = (id: string, nodeType: string, config: Record<string, unknown> = {}, label = id): WorkflowNodeSerialized =>
  ({ id, type: nodeType, position: { x: 0, y: 0 }, data: { label, nodeType, config } }) as WorkflowNodeSerialized;

const triage = {
  agentId: "wf_handle_request_triage",
  task: "Work out how urgent {{trigger.reason}} is",
  input: { petId: "{{pet.id}}" },
  outputFields: [
    { name: "urgency", type: "enum", values: ["routine", "soon", "emergency"], description: "How soon it needs a vet", required: true },
    { name: "questions", type: "array", description: "What to ask the owner", required: false },
  ],
  autonomy: "limited",
  minConfidence: 0.9,
  allowedWriteTools: ["book_visit"],
  maxActions: 2,
};

describe("the agent step in the palette", () => {
  it("is offered under AI Nodes, with plain wording, the Bot icon and the AI gradient", () => {
    const ai = NODE_CATEGORIES.find((c) => c.label === "AI Nodes")!;
    const item = ai.nodes.find((n) => n.id === "agent_step")!;
    expect(item).toBeTruthy();
    expect(item.type).toBe("agent_step");
    expect(item.label).toMatch(/assistant|agent/i);
    expect(item.icon).toBe("Bot");
    expect(item.gradient).toMatch(/^bg-gradient-to-br from-(purple|violet|fuchsia|pink|indigo)-/);
    // a fresh node starts safe: suggest-only, and a failure goes to a person
    expect(item.defaultConfig).toMatchObject({ autonomy: "suggest", onFailure: "human" });
  });

  it("has an in and an out handle only", () => {
    expect(catalogNode("agent_step")!.handles).toEqual({ in: true, out: true, else: false });
    expect(isBranchingNode("agent_step")).toBe(false);
    expect(visualFor("agent_step").icon).toBe("Bot");
  });

  it("needs an assistant or a brief, a task and at least one answer", () => {
    expect(catalogNode("agent_step")!.config.required).toEqual([["agentId", "agentBrief"], ["task"], ["outputFields"]]);
    expect(missingConfig("agent_step", {})).toEqual(["agentId|agentBrief", "task", "outputFields"]);
    expect(missingConfig("agent_step", { agentBrief: { purpose: "x", reads: [] }, task: "t", outputFields: [{ name: "a" }] })).toEqual([]);
    expect(missingConfig("agent_step", { agentId: "a", task: "t", outputFields: [] })).toEqual(["outputFields"]);
  });
});

describe("loading a workflow with an agent step", () => {
  it("leaves a top-level agent step alone and fills in data.nodeType when it is missing", () => {
    const [a] = normalizeWorkflowNodes([node("s", "agent_step", triage)]);
    expect(a.type).toBe("agent_step");
    expect(a.data.nodeType).toBe("agent_step");
    const bare = { id: "s", type: "agent_step", position: { x: 0, y: 0 }, data: { label: "S", config: triage } } as unknown as WorkflowNodeSerialized;
    expect(normalizeWorkflowNodes([bare])[0].data.nodeType).toBe("agent_step");
  });

  it("promotes the older action shape (actionType agent_step) like the other AI steps", () => {
    const [n] = normalizeWorkflowNodes([
      { id: "s", type: "action", position: { x: 0, y: 0 }, data: { label: "S", nodeType: "action", config: { actionType: "agent_step", task: "t" } } } as unknown as WorkflowNodeSerialized,
    ]);
    expect(n.type).toBe("agent_step");
    expect(n.data.nodeType).toBe("agent_step");
    expect((n.data.config as { task?: string }).task).toBe("t");
  });
});

describe("what a later step can pick from an agent step", () => {
  const nodes = [node("trigger_1", "trigger"), node("triage", "agent_step", triage, "Triage"), node("route", "decision"), node("before", "action")];
  const edges = [
    { source: "trigger_1", target: "triage" },
    { source: "triage", target: "route" },
    { source: "before", target: "trigger_1" },
  ];

  it("offers each answer as result.<name>, plus the standard fields, only to steps after it", () => {
    const after = collectWorkflowVariables({ nodes, edges, currentNodeId: "route" }).map((v) => v.path);
    expect(after).toContain("triage.result.urgency");
    expect(after).toContain("triage.result.questions");
    for (const f of ["needsHuman", "confidence", "summary", "proposals", "actions", "ok"]) expect(after).toContain(`triage.${f}`);

    const before = collectWorkflowVariables({ nodes, edges, currentNodeId: "trigger_1" }).map((v) => v.path);
    expect(before.some((p) => p.startsWith("triage."))).toBe(false);
  });

  it("types them and labels them with the step's name", () => {
    const vars = collectWorkflowVariables({ nodes, edges, currentNodeId: "route" });
    const urgency = vars.find((v) => v.path === "triage.result.urgency")!;
    expect(urgency.type).toBe("enum");
    expect(urgency.sourceLabel).toBe("Triage");
    expect(vars.find((v) => v.path === "triage.needsHuman")!.type).toBe("boolean");
  });

  it("copes with an answers list that is not a list", () => {
    const odd = [node("triage", "agent_step", { outputFields: "nope" }), node("route", "decision")];
    expect(() => collectWorkflowVariables({ nodes: odd, edges: [{ source: "triage", target: "route" }], currentNodeId: "route" })).not.toThrow();
  });
});

describe("the editor's own contract for the step", () => {
  it("declares what it takes and what it hands back", () => {
    const c = ACTION_CONTRACTS.agent_step;
    expect(c.label).toBe("Assistant step");
    expect(c.inputs.filter((i) => i.required).map((i) => i.name)).toEqual(["task", "outputFields"]);
    expect(c.outputs.map((o) => o.name)).toEqual(["ok", "needsHuman", "confidence", "summary", "result", "proposals", "actions"]);
    expect(ACTION_FIELD_SPECS.agent_step.fields.map((f) => f.key)).toEqual(
      expect.arrayContaining(["agentId", "task", "input", "outputFields", "autonomy", "onFailure"]),
    );
  });
});

describe("how the editor describes the step to the AI chat", () => {
  const wf = (config: Record<string, unknown>): WorkflowDefinition => ({
    id: "wf_1",
    name: "Handle appointment request",
    definition: {
      trigger: { type: "manual" },
      steps: [],
      nodes: [node("triage", "agent_step", config, "Triage")],
      edges: [],
    },
  });

  it("states the assistant, task, facts, answers, autonomy, limits and failure choice in plain words", () => {
    const text = buildWorkflowInstruction(wf(triage));
    expect(text).toContain("### [agent_step] Triage (id: triage)");
    expect(text).toContain("Assistant: wf_handle_request_triage");
    expect(text).toContain("Task: Work out how urgent {{trigger.reason}} is");
    expect(text).toContain("petId <- {{pet.id}}");
    expect(text).toContain("urgency (one of routine|soon|emergency): How soon it needs a vet");
    expect(text).toContain("questions (array, optional): What to ask the owner");
    expect(text).toContain("Autonomy: Limited (It may make the changes you list, only when it is confident enough");
    expect(text).toContain("Changes it may make: book_visit");
    expect(text).toContain("Only when at least 0.9 sure");
    expect(text).toContain("At most 2 changes at one time");
    expect(text).toContain("Limits: 6 turns, 60 seconds, 30000 tokens");
    expect(text).toContain("If it cannot finish: Send to a person");
    expect(text).toContain("Output: {result: {urgency, questions}, needsHuman, confidence, summary, proposals, actions, ok}");
    expect(text).toContain("### Agent steps:");
  });

  it("says suggest-only without any list of changes, and a planned assistant by its purpose", () => {
    const text = buildWorkflowInstruction(wf({ agentBrief: { purpose: "Triage requests", reads: ["pets"] }, task: "t", outputFields: [] }));
    expect(text).toContain("Assistant: to be created (Triage requests)");
    expect(text).toContain("Autonomy: Suggest (It only looks things up and suggests.");
    expect(text).not.toContain("Changes it may make");
  });

  it("does not add the agent section to a workflow without one", () => {
    const plain: WorkflowDefinition = { ...wf(triage), definition: { ...wf(triage).definition, nodes: [node("a", "action", { actionType: "db_query" })] } };
    expect(buildWorkflowInstruction(plain)).not.toContain("Agent steps");
  });
});
