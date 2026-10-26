/**
 * The agent step's properties panel, driven through the real NodePropertiesPanel (so the wiring is tested too):
 * the assistant picker and "create one for this step", the answers editor, the autonomy dial, limits, failure choice
 * and the plain-English problems.
 *
 * jsdom + manual createRoot + act() — same house style as the agent builder's tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (typeof window !== "undefined" && !(window as any).matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  })) as unknown as typeof window.matchMedia;
}

const apiGet = vi.fn(async (_url: string): Promise<unknown> => []);
const apiPost = vi.fn(async (_url: string, _body?: unknown): Promise<unknown> => ({}));
vi.mock("@/lib/api", () => ({
  api: {
    get: (url: string) => apiGet(url),
    post: (url: string, body?: unknown) => apiPost(url, body),
    put: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
  describeDetail: (d: unknown) => String(d ?? ""),
}));

import { NodePropertiesPanel } from "../NodePropertiesPanel";
import type { WorkflowNodeData, WorkflowNodeSerialized } from "@/types/workflow";

const LIST = [
  { id: "vet_chat", name: "Vet helper", description: "Answers questions from owners", node_count: 5 },
  { id: "wf_handle_request_triage", name: "Triage", description: "Works out how urgent a request is", node_count: 4 },
];
const DEFINITIONS: Record<string, unknown> = {
  wf_handle_request_triage: {
    nodes: [
      { data: { nodeType: "tool", label: "Find pet", config: { tool_name: "find_pet", tool_type: "data_engine", operation: "list" } } },
      { data: { nodeType: "tool", label: "Book visit", config: { tool_name: "book_visit", tool_type: "data_engine", operation: "create" } } },
      { data: { nodeType: "tool", label: "Tell owner", config: { tool_name: "tell_owner", tool_type: "api_call", method: "POST" } } },
    ],
  },
  vet_chat: { nodes: [] },
};

let container: HTMLDivElement;
let root: Root;
let current: WorkflowNodeData;
/** What the pretend platform lists as the project's assistants (a created one is added to it). */
let list: Array<{ id: string; name: string; description: string | null; node_count: number }>;
/** The list as the picker last received it, and whether a made assistant was ever chosen before the picker knew of it. */
let served: typeof list;
let chosenBeforeListed = false;

beforeEach(() => {
  list = [...LIST];
  served = [];
  chosenBeforeListed = false;
  apiGet.mockReset();
  apiPost.mockReset();
  apiGet.mockImplementation(async (url: string) => {
    if (url === "/api/projects/p1/agent-definitions") {
      // a real list takes a moment to arrive
      await new Promise((r) => setTimeout(r, 15));
      return (served = list);
    }
    const m = url.match(/^\/api\/projects\/p1\/agent-definitions\/([^/]+)$/);
    if (m && DEFINITIONS[m[1]]) return DEFINITIONS[m[1]];
    throw new Error(`unexpected GET ${url}`);
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const wait = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

const stepNode = (config: Record<string, unknown>, label = "Triage"): WorkflowNodeSerialized =>
  ({ id: "agent_step_1", type: "agent_step", position: { x: 0, y: 0 }, data: { label, nodeType: "agent_step", config } }) as WorkflowNodeSerialized;

interface MountOpts {
  config?: Record<string, unknown>;
  nodes?: WorkflowNodeSerialized[];
  edges?: Array<{ source: string; target: string }>;
}

async function mount(opts: MountOpts = {}) {
  const config = opts.config ?? {};
  const initial: WorkflowNodeData = { label: "Triage", nodeType: "agent_step" as never, config: config as never };
  current = initial;
  const nodes = opts.nodes ?? [stepNode(config)];
  function Harness() {
    const [data, setData] = useState<WorkflowNodeData>(initial);
    current = data;
    const id = (data.config as { agentId?: string }).agentId;
    if (id && !served.some((a) => a.id === id)) chosenBeforeListed = true;
    return (
      <NodePropertiesPanel
        nodeData={data}
        nodeId="agent_step_1"
        allNodes={nodes}
        allEdges={opts.edges}
        appModel={null}
        projectId="p1"
        workflowId="wf_1"
        onUpdate={(d) => setData((prev) => ({ ...prev, ...d }))}
        onClose={() => {}}
      />
    );
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(<QueryClientProvider client={qc}><Harness /></QueryClientProvider>);
  });
  await wait();
  // the lists take a moment to arrive: wait for them rather than guess how long
  for (let i = 0; i < 60 && /Looking for assistants|Reading this assistant/.test(container.textContent ?? ""); i++) await wait(25);
  return qc;
}

const cfg = () => current.config as Record<string, any>;
const q = <T extends Element = HTMLElement>(sel: string) => container.querySelector(sel) as T;
const byText = (sel: string, re: RegExp) => [...container.querySelectorAll(sel)].find((e) => re.test(e.textContent ?? "")) as HTMLElement;
const button = (re: RegExp) => byText("button", re);
const radio = (re: RegExp) => byText('[role="radio"]', re);

async function click(el: Element) {
  await act(async () => { (el as HTMLElement).click(); });
  await wait(10);
}
async function type(el: Element, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function choose(el: Element, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function blur(el: Element) {
  await act(async () => {
    (el as HTMLElement).focus();
    (el as HTMLElement).blur();
    el.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  });
}
const text = () => container.textContent ?? "";

const goodConfig = {
  agentId: "wf_handle_request_triage",
  task: "Work out how urgent {{trigger.reason}} is",
  outputFields: [{ name: "urgency", type: "enum", values: ["routine", "soon", "emergency"], description: "How soon", required: true }],
};

describe("assistant picker", () => {
  it("lists the project's assistants and tags the ones made for a workflow", async () => {
    await mount({ config: {} });
    const rows = [...container.querySelectorAll('[role="radiogroup"][aria-label="Assistant"] [role="radio"]')];
    expect(rows.map((r) => r.querySelector("span.truncate")?.textContent)).toEqual(["Vet helper", "Triage"]);
    expect(rows[0].textContent).not.toMatch(/Made for a workflow/);
    expect(rows[1].textContent).toMatch(/Made for a workflow/);
    expect(rows[1].textContent).toMatch(/Works out how urgent a request is/);
    expect(apiGet).toHaveBeenCalledWith("/api/projects/p1/agent-definitions");
  });

  it("saves the chosen assistant's id into the step and marks it chosen", async () => {
    await mount({ config: { agentBrief: { purpose: "Triage", reads: ["pets"] } } });
    await click(radio(/Vet helper/));
    expect(cfg().agentId).toBe("vet_chat");
    // the brief is only for while there is no assistant
    expect(cfg().agentBrief).toBeUndefined();
    expect(radio(/Vet helper/).getAttribute("aria-checked")).toBe("true");
    expect(radio(/Triage/).getAttribute("aria-checked")).toBe("false");
  });

  it("says plainly when the project has no assistants, and when the list cannot be loaded", async () => {
    apiGet.mockImplementation(async () => []);
    await mount();
    expect(text()).toMatch(/This project has no assistants yet/);
    act(() => root.unmount());
    root = createRoot(container);
    apiGet.mockImplementation(async () => { throw new Error("down"); });
    await mount();
    expect(text()).toMatch(/Could not load the assistants/);
  });

  it("asks for an assistant until one is chosen", async () => {
    await mount({ config: { task: "x" } });
    expect(q('[data-testid="issues-assistant"]').textContent).toBe("Pick an assistant for this step, or create one for it.");
    await click(radio(/Vet helper/));
    expect(q('[data-testid="issues-assistant"]')).toBeNull();
  });

  it("says when the chosen assistant is no longer in the project", async () => {
    await mount({ config: { ...goodConfig, agentId: "deleted_one" } });
    expect(q('[data-testid="issues-assistant"]').textContent).toMatch(/"deleted_one" cannot be found in this project/);
  });
});

describe("create an assistant for this step", () => {
  const openForm = async () => {
    await click(button(/Create an assistant for this step/));
    expect(q('[data-testid="brief-form"]')).toBeTruthy();
  };

  it("sends the brief, the workflow and the step, then chooses what came back and shows its warnings", async () => {
    apiPost.mockImplementation(async () => {
      // the platform now lists the new assistant
      list = [...list, { id: "wf_wf_1_agent_step_1", name: "Triage helper", description: null, node_count: 3 }];
      return {
        agentId: "wf_wf_1_agent_step_1",
        name: "Triage helper",
        tools: ["find_pet"],
        warnings: ["It asks the person before booking, as every change does."],
      };
    });
    await mount({ config: { task: "x" } });
    await openForm();
    await type(q("#brief-purpose"), "Work out how urgent a visit request is");
    await type(q("#brief-reads"), "pets\nvaccinations\n\nvet_schedules");
    await click(button(/Add a change/));
    await type(q('input[aria-label="Change 1 tool"]'), "book_visit");
    await type(q('input[aria-label="Change 1 reason"]'), "routine and easy to undo");
    await type(q("#brief-name"), "Triage helper");
    await click(button(/Create assistant/));
    await wait();

    expect(apiPost).toHaveBeenCalledTimes(1);
    const [url, body] = apiPost.mock.calls[0];
    expect(url).toBe("/api/projects/p1/agent-definitions/from-brief");
    expect(body).toEqual({
      brief: {
        purpose: "Work out how urgent a visit request is",
        reads: ["pets", "vaccinations", "vet_schedules"],
        mayChange: [{ tool: "book_visit", why: "routine and easy to undo" }],
      },
      workflowId: "wf_1",
      stepId: "agent_step_1",
      name: "Triage helper",
    });
    expect(cfg().agentId).toBe("wf_wf_1_agent_step_1");
    expect(q('[data-testid="brief-form"]')).toBeNull();
    // it is in the picker, chosen, and was only chosen once the picker knew of it (no flash of "cannot be found")
    expect(chosenBeforeListed).toBe(false);
    expect(radio(/Triage helper/).getAttribute("aria-checked")).toBe("true");
    expect(q('[data-testid="issues-assistant"]')).toBeNull();
    expect(q('[data-testid="assistant-made"]').textContent).toMatch(/Made "Triage helper" and chose it for this step/);
    expect(q('[data-testid="assistant-made"]').textContent).toMatch(/It asks the person before booking/);
    // the list is read again so the new assistant is in the picker (and the Agents tab)
    expect(apiGet.mock.calls.filter((c) => c[0] === "/api/projects/p1/agent-definitions").length).toBeGreaterThan(1);
  });

  it("leaves the name out when none was typed", async () => {
    apiPost.mockResolvedValue({ agentId: "wf_a", warnings: [] });
    await mount();
    await openForm();
    await type(q("#brief-purpose"), "Triage");
    await type(q("#brief-reads"), "pets");
    await click(button(/Create assistant/));
    await wait();
    expect(apiPost.mock.calls[0][1]).not.toHaveProperty("name");
    expect(apiPost.mock.calls[0][1]).toMatchObject({ brief: { purpose: "Triage", reads: ["pets"] } });
    expect(q('[data-testid="assistant-made"]').textContent).toMatch(/Made the assistant and chose it/);
  });

  it("shows the plain sentence when it fails, keeps the form, and changes nothing", async () => {
    apiPost.mockRejectedValue(new Error("There is no tool called book_visit in this app, so it cannot be allowed."));
    await mount({ config: { task: "x" } });
    await openForm();
    await type(q("#brief-purpose"), "Triage");
    await type(q("#brief-reads"), "pets");
    await click(button(/Create assistant/));
    await wait();
    expect(q('[data-testid="brief-form"] [role="alert"]').textContent).toBe(
      "There is no tool called book_visit in this app, so it cannot be allowed.",
    );
    expect(cfg().agentId).toBeUndefined();
    expect(q('[data-testid="brief-form"]')).toBeTruthy();
  });

  it("cannot be sent until it says what to do and what to read", async () => {
    await mount();
    await openForm();
    const send = () => button(/Create assistant/) as HTMLButtonElement;
    expect(send().disabled).toBe(true);
    await type(q("#brief-purpose"), "Triage");
    expect(send().disabled).toBe(true);
    expect(q('[data-testid="brief-form"]').textContent).toMatch(/List what it may read, one per line/);
    await type(q("#brief-reads"), "pets");
    expect(send().disabled).toBe(false);
    await click(button(/Add a change/));
    await type(q('input[aria-label="Change 1 tool"]'), "book_visit");
    expect(send().disabled).toBe(true);
    expect(q('[data-testid="brief-form"]').textContent).toMatch(/needs both the tool name and a reason/);
    await click(button(/Cancel/));
    expect(q('[data-testid="brief-form"]')).toBeNull();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("opens with a planned brief already filled in", async () => {
    await mount({ config: { agentBrief: { purpose: "Triage requests", reads: ["pets", "visits"], mayChange: [{ tool: "book_visit", why: "routine" }] } } });
    expect(text()).toMatch(/Planned assistant/);
    await openForm();
    expect((q("#brief-purpose") as HTMLTextAreaElement).value).toBe("Triage requests");
    expect((q("#brief-reads") as HTMLTextAreaElement).value).toBe("pets\nvisits");
    expect((q('input[aria-label="Change 1 tool"]') as HTMLInputElement).value).toBe("book_visit");
  });
});

describe("the task and the variable picker", () => {
  it("takes the task text and puts a picked variable into it", async () => {
    await mount({
      config: goodConfig,
      nodes: [
        { id: "trigger_1", type: "trigger", position: { x: 0, y: 0 }, data: { label: "Start", nodeType: "trigger", config: {} } } as WorkflowNodeSerialized,
        { id: "lookup", type: "action", position: { x: 0, y: 0 }, data: { label: "Look up owner", nodeType: "action", config: { actionType: "db_query" } } } as WorkflowNodeSerialized,
        stepNode(goodConfig),
      ],
      edges: [{ source: "trigger_1", target: "lookup" }, { source: "lookup", target: "agent_step_1" }],
    });
    const task = q<HTMLTextAreaElement>("#agent-task");
    expect(task.value).toBe(goodConfig.task);
    await type(task, "Triage ");
    expect(cfg().task).toBe("Triage ");
    const picker = [...container.querySelectorAll("button")].find((b) => b.textContent === "lookup.output");
    expect(picker, "an earlier step's output is on offer").toBeTruthy();
    await click(picker!);
    expect(cfg().task).toBe("Triage {{lookup.output}}");
  });

  it("keeps the facts to hand over as a name to variable list, and does not save a fact with no name", async () => {
    await mount({ config: { ...goodConfig, input: { petId: "{{pet.id}}" } } });
    expect(text()).toMatch(/Facts to hand over/);
    expect(q<HTMLInputElement>('input[aria-label="Fact 1 name"]').value).toBe("petId");
    expect(q<HTMLInputElement>('input[aria-label="Fact 1 value"]').value).toBe("{{pet.id}}");
    await click(button(/Add a fact/));
    expect(cfg().input).toEqual({ petId: "{{pet.id}}" });
    expect(text()).toMatch(/One of the facts has no name yet, so it is not saved/);
    await type(q('input[aria-label="Fact 2 name"]'), "ownerName");
    await type(q('input[aria-label="Fact 2 value"]'), "{{trigger.ownerName}}");
    expect(cfg().input).toEqual({ petId: "{{pet.id}}", ownerName: "{{trigger.ownerName}}" });
    expect(text()).not.toMatch(/has no name yet/);
    await type(q('input[aria-label="Fact 2 name"]'), "petId");
    expect(text()).toContain('Two facts are both called "petId". Only the last one is kept.');
    await click(q('button[aria-label="Remove fact 2"]'));
    expect(cfg().input).toEqual({ petId: "{{pet.id}}" });
  });

  it("writes a picked variable into a fact", async () => {
    await mount({
      config: { ...goodConfig, input: { who: "" } },
      nodes: [
        { id: "trigger_1", type: "trigger", position: { x: 0, y: 0 }, data: { label: "Start", nodeType: "trigger", config: {} } } as WorkflowNodeSerialized,
        stepNode(goodConfig),
      ],
      edges: [{ source: "trigger_1", target: "agent_step_1" }],
    });
    await choose(q('select[aria-label="Fact 1 pick a variable"]'), "trigger.requesterId");
    expect(cfg().input).toEqual({ who: "{{trigger.requesterId}}" });
    expect(q<HTMLInputElement>('input[aria-label="Fact 1 value"]').value).toBe("{{trigger.requesterId}}");
  });
});

describe("what it hands back", () => {
  it("adds an answer with a safe default name and lists the always-present fields", async () => {
    await mount({ config: { ...goodConfig, outputFields: [] } });
    expect(q('[data-testid="issues-answers"]').textContent).toMatch(/Add at least one answer/);
    await click(button(/Add an answer/));
    expect(cfg().outputFields).toEqual([{ name: "answer1", type: "string", description: "", required: true }]);
    expect(q('[data-testid="issues-answers"]')).toBeNull();
    for (const f of ["needsHuman", "confidence", "summary", "proposals", "actions", "ok"]) {
      expect(byText("code", new RegExp(`^${f}$`)), f).toBeTruthy();
    }
    expect(text()).toContain("{{agent_step_1.result.name}}");
  });

  it("refuses a name that breaks the pattern, with the rule in words", async () => {
    await mount({ config: goodConfig });
    const name = q<HTMLInputElement>('input[aria-label="Answer 1 name"]');
    await type(name, "Urgent Level");
    expect(cfg().outputFields[0].name).toBe("Urgent Level");
    expect(name.getAttribute("aria-invalid")).toBe("true");
    // the sentence sits under the answer it is about, once
    expect(q('[data-testid="answer-row"]').textContent).toContain(
      '"Urgent Level" cannot be a name. A name starts with a small letter and uses only letters, numbers and underscores.',
    );
    expect(q('[data-testid="issues-answers"]')).toBeNull();
    await type(name, "urgentLevel_2");
    expect(name.getAttribute("aria-invalid")).toBe("false");
    expect(q('[data-testid="issues-answers"]')).toBeNull();
  });

  it("refuses two answers with the same name", async () => {
    await mount({ config: goodConfig });
    await click(button(/Add an answer/));
    await type(q('input[aria-label="Answer 2 name"]'), "urgency");
    expect(text()).toContain('Two answers are both called "urgency". Each name must be different.');
    await type(q('input[aria-label="Answer 2 name"]'), "reason");
    expect(text()).not.toContain("Two answers are both called");
  });

  it("asks for allowed values on a pick-one answer, and keeps a trailing comma while typing", async () => {
    await mount({ config: { ...goodConfig, outputFields: [{ name: "level", type: "string", description: "" }] } });
    expect(q('input[aria-label="Answer 1 allowed values"]')).toBeNull();
    await choose(q('select[aria-label="Answer 1 type"]'), "enum");
    expect(cfg().outputFields[0].type).toBe("enum");
    expect(cfg().outputFields[0].values).toEqual([]);
    expect(q('[data-testid="answer-row"]').textContent).toContain('The answer "level" is a pick-one list, so give it at least one allowed value.');
    const values = q<HTMLInputElement>('input[aria-label="Answer 1 allowed values"]');
    await type(values, "routine, ");
    expect(values.value).toBe("routine, ");
    expect(cfg().outputFields[0].values).toEqual(["routine"]);
    await type(values, "routine, soon, emergency");
    expect(cfg().outputFields[0].values).toEqual(["routine", "soon", "emergency"]);
    expect(q('[data-testid="issues-answers"]')).toBeNull();
    // going back to text drops the list
    await choose(q('select[aria-label="Answer 1 type"]'), "string");
    expect(cfg().outputFields[0].values).toBeUndefined();
  });

  it("stores the description and the must-always-answer switch, and removes an answer", async () => {
    await mount({ config: goodConfig });
    await type(q('input[aria-label="Answer 1 description"]'), "How soon a vet must see the pet");
    expect(cfg().outputFields[0].description).toBe("How soon a vet must see the pet");
    const must = container.querySelector('[data-testid="answer-row"] input[type="checkbox"]') as HTMLInputElement;
    expect(must.checked).toBe(true);
    await click(must);
    expect(cfg().outputFields[0].required).toBe(false);
    await click(q('button[aria-label="Remove answer 1"]'));
    expect(cfg().outputFields).toEqual([]);
  });

  it("says when a later step reads an answer that is not there", async () => {
    await mount({
      config: goodConfig,
      nodes: [
        stepNode(goodConfig),
        { id: "route", type: "decision", position: { x: 0, y: 0 }, data: { label: "Route by urgency", nodeType: "decision", config: { expression: "{{agent_step_1.result.urgncy}} == 'soon'" } } } as WorkflowNodeSerialized,
      ],
      edges: [{ source: "agent_step_1", target: "route" }],
    });
    expect(q('[data-testid="issues-answers"]').textContent).toBe(
      'The step "Route by urgency" reads "{{agent_step_1.result.urgncy}}", but this step does not hand back an answer called "urgncy".',
    );
  });
});

describe("the autonomy dial", () => {
  it("starts on Suggest with the one-sentence explanations, and shows nothing about changes", async () => {
    await mount({ config: goodConfig });
    const dial = q('[role="radiogroup"][aria-label="How much it may do by itself"]');
    const choices = [...dial.querySelectorAll('[role="radio"]')];
    expect(choices.map((c) => c.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
    expect(choices.map((c) => c.querySelector("span")!.textContent)).toEqual(["Suggest", "Limited", "Full"]);
    expect(dial.textContent).toContain("It only looks things up and suggests. A person or a later step makes any change.");
    expect(dial.textContent).toContain("It may make the changes you list, only when it is confident enough and only a few at a time. Anything else goes to a person.");
    expect(dial.textContent).toContain("It may make the changes you list on its own, up to a limit.");
    expect(q('[data-testid="autonomy-warning"]')).toBeNull();
    expect(container.querySelector("#agent-min-confidence")).toBeNull();
    expect(container.querySelector("#agent-max-actions")).toBeNull();
  });

  it("Limited reveals the warning, the assistant's data-changing tools, the confidence slider and the change limit", async () => {
    await mount({ config: goodConfig });
    await click(radio(/^Limited/));
    await wait();
    expect(cfg().autonomy).toBe("limited");
    expect(cfg().minConfidence).toBe(0.85);
    expect(cfg().maxActions).toBe(3);
    expect(q('[data-testid="autonomy-warning"]').textContent).toBe(
      "Changes made by the assistant happen without anyone looking first. Use this only for things that are easy to undo.",
    );
    // only the tools that change data are offered (not find_pet)
    const labels = [...container.querySelectorAll("fieldset label")].map((l) => l.textContent);
    expect(labels).toEqual(["book_visit changes data", "tell_owner changes data"]);
    expect(q('[data-testid="confidence-value"]').textContent).toBe("85%");
    expect(container.querySelector("#agent-max-actions")).toBeTruthy();
    // nothing is allowed yet, so the step cannot build
    expect(q('[data-testid="issues-autonomy"]').textContent).toContain(
      "You chose Limited, but listed no changes the assistant may make. Pick at least one, or switch to Suggest.",
    );
    // pick one: the message goes, and it is saved
    await click(container.querySelector('fieldset input[type="checkbox"]')!);
    expect(cfg().allowedWriteTools).toEqual(["book_visit"]);
    expect(q('[data-testid="issues-autonomy"]').textContent).not.toContain("You chose Limited");
    // the other tool is noted as suggestions only
    expect(q('[data-testid="issues-autonomy"]').textContent).toContain("(tell_owner)");
    // the slider moves the confidence
    const slider = q<HTMLInputElement>("#agent-min-confidence");
    await type(slider, "0.95");
    expect(cfg().minConfidence).toBe(0.95);
    expect(q('[data-testid="confidence-value"]').textContent).toBe("95%");
  });

  it("Full has no confidence slider and says the same warning", async () => {
    await mount({ config: goodConfig });
    await click(radio(/^Full/));
    await wait();
    expect(cfg().autonomy).toBe("full");
    expect(cfg().minConfidence).toBeUndefined();
    expect(container.querySelector("#agent-min-confidence")).toBeNull();
    expect(q('[data-testid="autonomy-warning"]')).toBeTruthy();
    expect(q('[data-testid="issues-autonomy"]').textContent).toContain("You chose Full, but listed no changes");
  });

  it("going back to Suggest clears what was allowed, and coming back restores the picks", async () => {
    await mount({ config: { ...goodConfig, autonomy: "limited", allowedWriteTools: ["book_visit"], minConfidence: 0.9, maxActions: 2 } });
    await wait();
    await click(radio(/^Suggest/));
    expect(cfg().autonomy).toBe("suggest");
    expect(cfg().allowedWriteTools).toBeUndefined();
    expect(cfg().minConfidence).toBeUndefined();
    await click(radio(/^Limited/));
    expect(cfg().allowedWriteTools).toEqual(["book_visit"]);
    expect(cfg().minConfidence).toBe(0.85);
  });

  it("says when the assistant has no tool that could change anything", async () => {
    await mount({ config: { ...goodConfig, agentId: "vet_chat" } });
    await click(radio(/^Limited/));
    await wait();
    expect(text()).toMatch(/This assistant has no tools that change data, so there is nothing to allow/);
  });

  it("takes a typed list when the assistant's tools cannot be read, and says so", async () => {
    apiGet.mockImplementation(async (url: string) => {
      if (url === "/api/projects/p1/agent-definitions") return LIST;
      throw new Error("nope");
    });
    await mount({ config: goodConfig });
    await click(radio(/^Limited/));
    await wait();
    expect(text()).toMatch(/We could not read this assistant's tools, so type the names of the tools it may use to make changes, one per line/);
    await type(q("#agent-write-tools"), "book_visit\nnotify");
    expect(cfg().allowedWriteTools).toEqual(["book_visit", "notify"]);
  });

  it("refuses a listed change that is not one of the assistant's tools", async () => {
    await mount({ config: { ...goodConfig, autonomy: "full", allowedWriteTools: ["teleport"] } });
    await wait();
    expect(q('[data-testid="issues-autonomy"]').textContent).toContain('"teleport" is not one of this assistant\'s tools.');
  });
});

describe("limits", () => {
  const limitBox = (id: string) => q<HTMLInputElement>(`#${id}`);

  it("show the contract defaults and ranges", async () => {
    await mount({ config: goodConfig });
    expect(limitBox("agent-max-turns").value).toBe("6");
    expect(limitBox("agent-timeout").value).toBe("60");
    expect(limitBox("agent-max-tokens").value).toBe("30000");
    expect(text()).toContain("1 to 12");
    expect(text()).toContain("5 to 300");
    expect(text()).toContain("1,000 to 100,000");
  });

  it("clamp into range when the person finishes typing", async () => {
    await mount({ config: { ...goodConfig, autonomy: "full", allowedWriteTools: ["book_visit"] } });
    await wait();
    const cases: Array<[string, string, number, string]> = [
      ["agent-max-turns", "99", 12, "maxTurns"],
      ["agent-max-turns", "0", 1, "maxTurns"],
      ["agent-timeout", "1", 5, "timeoutSec"],
      ["agent-timeout", "9999", 300, "timeoutSec"],
      ["agent-max-tokens", "50", 1000, "maxTokens"],
      ["agent-max-tokens", "999999", 100000, "maxTokens"],
      ["agent-max-actions", "50", 10, "maxActions"],
      ["agent-max-actions", "0", 1, "maxActions"],
    ];
    for (const [id, typed, expected, key] of cases) {
      await type(limitBox(id), typed);
      await blur(limitBox(id));
      expect(cfg()[key], `${key} after typing ${typed}`).toBe(expected);
      expect(limitBox(id).value).toBe(String(expected));
    }
  });

  it("do not save half-typed numbers (5 on the way to 500)", async () => {
    await mount({ config: goodConfig });
    await type(limitBox("agent-timeout"), "5");
    expect(cfg().timeoutSec).toBeUndefined();
    await type(limitBox("agent-timeout"), "500");
    await blur(limitBox("agent-timeout"));
    expect(cfg().timeoutSec).toBe(300);
  });

  it("name a saved value that is out of range", async () => {
    await mount({ config: { ...goodConfig, maxTurns: 40, timeoutSec: 1, maxTokens: 5 } });
    const t = q('[data-testid="issues-limits"]').textContent!;
    expect(t).toContain("Turns has to be a whole number from 1 to 12.");
    expect(t).toContain("Time limit has to be a whole number of seconds from 5 to 300.");
    expect(t).toContain("Size limit has to be a whole number from 1,000 to 100,000.");
  });
});

describe("if it cannot finish", () => {
  it("defaults to sending the step to a person and saves another choice", async () => {
    await mount({ config: goodConfig });
    const group = q('[role="radiogroup"][aria-label="If it cannot finish"]');
    const checked = [...group.querySelectorAll('[role="radio"]')].filter((r) => r.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(1);
    expect(checked[0].textContent).toMatch(/^Send to a person/);
    await click(radio(/^Stop the workflow/));
    expect(cfg().onFailure).toBe("fail");
    await click(radio(/^Carry on without it/));
    expect(cfg().onFailure).toBe("skip");
  });
});

describe("the whole step", () => {
  it("shows no problems for a complete step, and counts them for an empty one", async () => {
    await mount({ config: goodConfig });
    expect(container.querySelectorAll('[role="alert"]')).toHaveLength(0);
    expect(text()).not.toMatch(/things? to fix/);
    act(() => root.unmount());
    root = createRoot(container);
    await mount({ config: {} });
    // no assistant, no task, no answers
    expect(text()).toMatch(/3 things to fix before this step will build\./);
    expect(q('[data-testid="issues-task"]').textContent).toBe("Say what the assistant should do this time.");
  });

  it("has no button, in any state, with brackets or ampersands in its name", async () => {
    await mount({ config: { ...goodConfig, autonomy: "limited", allowedWriteTools: ["book_visit"], input: { petId: "{{pet.id}}" } } });
    await wait();
    await click(button(/Create an assistant for this step/));
    await click(button(/Add a change/));
    const names = () =>
      [...container.querySelectorAll("button")].flatMap((b) => [b.textContent ?? "", b.getAttribute("aria-label") ?? ""]);
    expect(names().length).toBeGreaterThan(10);
    for (const n of names()) expect(n, `button name "${n}"`).not.toMatch(/[\[\]{}()<>&]/);
  });
});
