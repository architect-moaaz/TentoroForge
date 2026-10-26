import { describe, it, expect } from "vitest";
import {
  AUTONOMY_CHOICES,
  AUTONOMY_WARNING,
  FAILURE_CHOICES,
  STEP_LIMITS,
  agentStepIssues,
  agentStepVariables,
  assistantTools,
  briefProblem,
  clampLimit,
  draftFromBrief,
  outputNameProblem,
  parseNameList,
  readFromBrief,
  readsOfStep,
  stepsAfter,
  toBrief,
  type AssistantTool,
} from "./agent-step";
import type { WorkflowNodeSerialized } from "@/types/workflow";

const node = (id: string, nodeType: string, config: Record<string, unknown> = {}, label = id): WorkflowNodeSerialized =>
  ({ id, type: nodeType, position: { x: 0, y: 0 }, data: { label, nodeType, config } }) as WorkflowNodeSerialized;

const goodConfig = {
  agentId: "wf_handle_request_triage",
  task: "Work out how urgent {{trigger.reason}} is",
  outputFields: [
    { name: "urgency", type: "enum", values: ["routine", "soon", "emergency"], description: "How soon", required: true },
    { name: "reason", type: "string", description: "Why" },
  ],
};

const run = (config: Record<string, unknown>, more: Partial<Parameters<typeof agentStepIssues>[0]> = {}) =>
  agentStepIssues({ config: config as never, stepId: "agent_step_1", nodes: [], ...more });
const errors = (config: Record<string, unknown>, more = {}) => run(config, more).filter((i) => i.level === "error").map((i) => i.text);

describe("the three autonomy choices", () => {
  it("say, in plain words, what each one allows", () => {
    expect(AUTONOMY_CHOICES.map((c) => c.value)).toEqual(["suggest", "limited", "full"]);
    expect(AUTONOMY_CHOICES[0].explain).toBe("It only looks things up and suggests. A person or a later step makes any change.");
    expect(AUTONOMY_CHOICES[1].explain).toBe(
      "It may make the changes you list, only when it is confident enough and only a few at a time. Anything else goes to a person.",
    );
    expect(AUTONOMY_CHOICES[2].explain).toBe("It may make the changes you list on its own, up to a limit.");
    expect(AUTONOMY_WARNING).toBe(
      "Changes made by the assistant happen without anyone looking first. Use this only for things that are easy to undo.",
    );
  });

  it("offers three ways to fail, and the default one is the safe one", () => {
    expect(FAILURE_CHOICES.map((c) => c.value)).toEqual(["human", "skip", "fail"]);
    expect(FAILURE_CHOICES[0].label).toBe("Send to a person");
  });
});

describe("limits", () => {
  it("keep the contract's ranges and defaults", () => {
    expect(STEP_LIMITS.maxTurns).toMatchObject({ min: 1, max: 12, default: 6 });
    expect(STEP_LIMITS.timeoutSec).toMatchObject({ min: 5, max: 300, default: 60 });
    expect(STEP_LIMITS.maxTokens).toMatchObject({ min: 1000, max: 100000, default: 30000 });
    expect(STEP_LIMITS.maxActions).toMatchObject({ min: 1, max: 10, default: 3 });
    expect(STEP_LIMITS.minConfidence).toMatchObject({ min: 0, max: 1, default: 0.85 });
  });

  it("clamp into range, round whole numbers, and fall back to the default for rubbish", () => {
    expect(clampLimit("maxTurns", 99)).toBe(12);
    expect(clampLimit("maxTurns", 0)).toBe(1);
    expect(clampLimit("maxTurns", "4.6")).toBe(5);
    expect(clampLimit("timeoutSec", 1)).toBe(5);
    expect(clampLimit("timeoutSec", 9999)).toBe(300);
    expect(clampLimit("maxTokens", 50)).toBe(1000);
    expect(clampLimit("maxActions", 50)).toBe(10);
    expect(clampLimit("minConfidence", 7)).toBe(1);
    expect(clampLimit("minConfidence", -1)).toBe(0);
    expect(clampLimit("minConfidence", "0.9")).toBe(0.9);
    expect(clampLimit("maxTurns", "abc")).toBe(6);
  });
});

describe("answer names", () => {
  it("must match the contract's pattern and be unique", () => {
    expect(outputNameProblem("urgency", [])).toBeNull();
    expect(outputNameProblem("suggestedVet_2", ["urgency"])).toBeNull();
    expect(outputNameProblem("", [])).toBe("Give this answer a name.");
    expect(outputNameProblem("Urgency", [])).toMatch(/cannot be a name\. A name starts with a small letter/);
    expect(outputNameProblem("2fast", [])).toMatch(/cannot be a name/);
    expect(outputNameProblem("has space", [])).toMatch(/cannot be a name/);
    expect(outputNameProblem("urgency", ["urgency"])).toBe('Two answers are both called "urgency". Each name must be different.');
  });
});

describe("agent step variables for later steps", () => {
  it("offer result.<name> for each answer plus the standard fields", () => {
    const vars = agentStepVariables("triage", goodConfig as never);
    const paths = vars.map((v) => v.path);
    expect(paths).toContain("triage.result.urgency");
    expect(paths).toContain("triage.result.reason");
    for (const std of ["needsHuman", "confidence", "summary", "proposals", "actions", "ok"]) {
      expect(paths).toContain(`triage.${std}`);
    }
    expect(vars.find((v) => v.path === "triage.result.urgency")!.type).toBe("enum");
    expect(vars.find((v) => v.path === "triage.needsHuman")!.type).toBe("boolean");
  });
});

describe("later steps that read an answer", () => {
  const nodes = [
    node("agent_step_1", "agent_step", goodConfig),
    node("decide", "decision", { expression: "{{agent_step_1.result.urgency}} == 'emergency'" }, "Decide"),
    node("mail", "action", { inputMappings: [{ name: "to", source: "variable", value: "agent_step_1.result.ownerEmail" }] }, "Email owner"),
    node("earlier", "action", { description: "{{agent_step_1.result.nope}}" }, "Earlier"),
  ];
  const edges = [
    { source: "agent_step_1", target: "decide" },
    { source: "decide", target: "mail" },
    { source: "earlier", target: "agent_step_1" },
  ];

  it("finds only the later steps, with or without braces", () => {
    expect(stepsAfter(edges, "agent_step_1")).toEqual(new Set(["decide", "mail"]));
    const reads = readsOfStep(nodes, edges, "agent_step_1");
    expect(reads.map((r) => `${r.stepId}:${r.field}`).sort()).toEqual(["decide:urgency", "mail:ownerEmail"]);
  });

  it("survives a loop in the graph and a step with unreadable settings", () => {
    const loop = [...edges, { source: "mail", target: "agent_step_1" }];
    expect(() => readsOfStep(nodes, loop, "agent_step_1")).not.toThrow();
    const odd = [...nodes, { id: "x", data: undefined } as unknown as WorkflowNodeSerialized];
    expect(() => readsOfStep(odd, [...edges, { source: "mail", target: "x" }], "agent_step_1")).not.toThrow();
  });

  it("does not mistake another step whose name ends the same", () => {
    const n2 = [node("agent_step_1", "agent_step", goodConfig), node("b", "action", { x: "my_agent_step_1.result.zzz" })];
    expect(readsOfStep(n2, [{ source: "agent_step_1", target: "b" }], "agent_step_1")).toEqual([]);
  });
});

describe("the assistant's tools", () => {
  const def = {
    nodes: [
      { data: { nodeType: "system_prompt", config: {} } },
      { data: { nodeType: "tool", label: "Find pet", config: { tool_name: "find_pet", tool_type: "data_engine", operation: "list" } } },
      { data: { nodeType: "tool", label: "Book", config: { tool_name: "book_visit", tool_type: "data_engine", operation: "create" } } },
      { data: { nodeType: "tool", label: "Ping", config: { tool_name: "ping", tool_type: "api_call", method: "GET" } } },
      { data: { nodeType: "tool", label: "Notify", config: { tool_name: "notify", tool_type: "api_call", method: "POST" } } },
      { data: { nodeType: "tool", label: "Run", config: { tool_name: "run_other", tool_type: "workflow", workflow_id: "wf_9" } } },
      { data: { nodeType: "tool", label: "Fn", config: { tool_name: "do thing", tool_type: "function" } } },
      { data: { nodeType: "tool", label: "Fn again", config: { tool_name: "do thing", tool_type: "function" } } },
      { data: { nodeType: "tool", label: "Q", config: { tool_name: "q", tool_type: "db_query", query: "SELECT 1" } } },
      { data: { nodeType: "tool", label: "Q2", config: { tool_name: "q2", tool_type: "db_query", query: "delete from x" } } },
    ],
  };

  it("sorts them into changes, might change, and only reads, with the app's names", () => {
    const tools = assistantTools(def);
    const by = Object.fromEntries(tools.map((t) => [t.name, t.changes]));
    expect(by).toEqual({
      find_pet: "no",
      book_visit: "yes",
      ping: "no",
      notify: "yes",
      run_other: "yes",
      do_thing: "maybe",
      do_thing_2: "maybe",
      q: "no",
      q2: "maybe",
    });
    expect(tools.find((t) => t.name === "run_other")!.workflowId).toBe("wf_9");
  });

  it("gives nothing for a definition with no drawing", () => {
    expect(assistantTools(null)).toEqual([]);
    expect(assistantTools({})).toEqual([]);
  });
});

describe("what is wrong with the step, in plain words", () => {
  it("is happy with a complete suggest-only step", () => {
    expect(run(goodConfig)).toEqual([]);
  });

  it("asks for an assistant when there is none, but only notes a planned one", () => {
    expect(errors({ ...goodConfig, agentId: undefined })).toEqual(["Pick an assistant for this step, or create one for it."]);
    const planned = run({ ...goodConfig, agentId: undefined, agentBrief: { purpose: "Triage", reads: ["pets"] } });
    expect(planned.every((i) => i.level === "note")).toBe(true);
    expect(planned[0].text).toMatch(/has not been made yet/);
  });

  it("says when the chosen assistant is not in the project", () => {
    expect(errors(goodConfig, { assistantIds: ["other"] })).toEqual([
      'The assistant "wf_handle_request_triage" cannot be found in this project. Pick another one, or create one for this step.',
    ]);
    expect(errors(goodConfig, { assistantIds: ["wf_handle_request_triage"] })).toEqual([]);
  });

  it("asks for the task", () => {
    expect(errors({ ...goodConfig, task: "  " })).toEqual(["Say what the assistant should do this time."]);
  });

  it("asks for at least one answer", () => {
    expect(errors({ ...goodConfig, outputFields: [] })).toEqual([
      "Add at least one answer for the assistant to hand back. Later steps can only read what is listed here.",
    ]);
  });

  it("names a bad answer, a repeated answer (once) and a pick-one list with no values", () => {
    const e = errors({
      ...goodConfig,
      outputFields: [
        { name: "Bad Name", type: "string", description: "" },
        { name: "same", type: "string", description: "" },
        { name: "same", type: "number", description: "" },
        { name: "level", type: "enum", values: [], description: "" },
      ],
    });
    expect(e).toContain('"Bad Name" cannot be a name. A name starts with a small letter and uses only letters, numbers and underscores.');
    expect(e.filter((t) => t.startsWith('Two answers are both called "same"'))).toHaveLength(1);
    expect(e).toContain('The answer "level" is a pick-one list, so give it at least one allowed value.');
  });

  it("says when a later step reads an answer that does not exist", () => {
    const nodes = [
      node("agent_step_1", "agent_step", goodConfig),
      node("decide", "decision", { expression: "{{agent_step_1.result.urgncy}} == 'soon'" }, "Route by urgency"),
    ];
    const e = errors(goodConfig, { nodes, edges: [{ source: "agent_step_1", target: "decide" }] });
    expect(e).toEqual([
      'The step "Route by urgency" reads "{{agent_step_1.result.urgncy}}", but this step does not hand back an answer called "urgncy".',
    ]);
  });

  it("wants write tools for Limited and for Full, never for Suggest", () => {
    expect(errors({ ...goodConfig, autonomy: "limited" })).toEqual([
      "You chose Limited, but listed no changes the assistant may make. Pick at least one, or switch to Suggest.",
    ]);
    expect(errors({ ...goodConfig, autonomy: "full" })).toEqual([
      "You chose Full, but listed no changes the assistant may make. Pick at least one, or switch to Suggest.",
    ]);
    expect(errors({ ...goodConfig, autonomy: "limited", allowedWriteTools: ["book_visit"] })).toEqual([]);
    expect(errors({ ...goodConfig, autonomy: "suggest" })).toEqual([]);
  });

  it("checks the listed changes against the assistant's real tools, and notes the ones left out", () => {
    const tools: AssistantTool[] = [
      { name: "book_visit", changes: "yes" },
      { name: "notify", changes: "yes" },
      { name: "find_pet", changes: "no" },
    ];
    const cfg = { ...goodConfig, autonomy: "limited", allowedWriteTools: ["book_visit", "teleport"] };
    expect(errors(cfg, { tools })).toEqual(['"teleport" is not one of this assistant\'s tools.']);
    const notes = run(cfg, { tools }).filter((i) => i.level === "note");
    expect(notes[0].text).toBe(
      "This assistant also has tools that change data and are not on your list (notify). Those only ever become suggestions.",
    );
    const suggest = run(goodConfig, { tools }).filter((i) => i.level === "note");
    expect(suggest[0].text).toMatch(/In this step they only ever become suggestions/);
  });

  it("refuses an assistant that could start the workflow it works in", () => {
    const tools: AssistantTool[] = [{ name: "again", changes: "yes", workflowId: "wf_1" }];
    expect(errors(goodConfig, { tools, workflowId: "wf_1" })).toEqual([
      "This assistant can start the very workflow it works in, which would make it loop. Pick a different assistant, or take that tool off it.",
    ]);
    expect(errors(goodConfig, { tools, workflowId: "wf_2" })).toEqual([]);
  });

  it("names every limit that is out of range", () => {
    const e = errors({ ...goodConfig, maxTurns: 13, timeoutSec: 2, maxTokens: 10, maxActions: 11 });
    expect(e).toEqual([
      "Changes at one time has to be a whole number from 1 to 10.",
      "Turns has to be a whole number from 1 to 12.",
      "Time limit has to be a whole number of seconds from 5 to 300.",
      "Size limit has to be a whole number from 1,000 to 100,000.",
    ]);
    expect(errors({ ...goodConfig, autonomy: "limited", allowedWriteTools: ["x"], minConfidence: 1.5 })).toEqual([
      "How sure it must be has to be a number from 0 to 1.",
    ]);
    // a confidence left over from a time it was Limited does not matter when it is not
    expect(errors({ ...goodConfig, minConfidence: 1.5 })).toEqual([]);
  });

  it("accepts what is missing as the defaults, and checks the failure choice", () => {
    expect(errors({ ...goodConfig, maxTurns: undefined, onFailure: undefined })).toEqual([]);
    expect(errors({ ...goodConfig, onFailure: "explode" })).toEqual([
      "Choose what happens when the assistant cannot finish: send to a person, carry on, or stop.",
    ]);
  });
});

describe("the brief for a new assistant", () => {
  it("turns a typed list into names, dropping blanks and repeats", () => {
    expect(parseNameList("pets\n\n vaccinations ,pets\nvet_schedules")).toEqual(["pets", "vaccinations", "vet_schedules"]);
  });

  it("is not ready until it says what to do and what to read, and each change has both parts", () => {
    const ok = { purpose: "Triage", reads: "pets", mayChange: [] };
    expect(briefProblem(ok)).toBeNull();
    expect(briefProblem({ ...ok, purpose: " " })).toBe("Say what the assistant should do.");
    expect(briefProblem({ ...ok, reads: "\n" })).toBe("List what it may read, one per line.");
    expect(briefProblem({ ...ok, purpose: "x".repeat(601) })).toBe("Keep it under 600 characters.");
    expect(briefProblem({ ...ok, mayChange: [{ tool: "book", why: "" }] })).toBe(
      "Each change it may make needs both the tool name and a reason.",
    );
  });

  it("builds the contract's brief shape and round-trips back into the form", () => {
    const brief = toBrief({ purpose: " Triage ", reads: "pets\nvaccinations", mayChange: [{ tool: "book", why: "routine" }, { tool: "", why: "" }] });
    expect(brief).toEqual({ purpose: "Triage", reads: ["pets", "vaccinations"], mayChange: [{ tool: "book", why: "routine" }] });
    expect(toBrief({ purpose: "x", reads: "a", mayChange: [] })).toEqual({ purpose: "x", reads: ["a"] });
    expect(draftFromBrief(brief)).toEqual({ purpose: "Triage", reads: "pets\nvaccinations", mayChange: [{ tool: "book", why: "routine" }] });
  });

  it("reads the platform's answer, tolerating a different shape for warnings", () => {
    expect(readFromBrief({ agentId: "wf_a", name: "A", tools: [], warnings: ["w1", { message: "w2" }] })).toEqual({
      agentId: "wf_a", name: "A", warnings: ["w1", "w2"],
    });
    expect(readFromBrief({ name: "A" })).toBeNull();
    expect(readFromBrief(null)).toBeNull();
  });
});
