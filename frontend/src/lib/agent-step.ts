/**
 * The agent step, as the workflow editor sees it: the logic behind the panel. No React, no network.
 *
 * An agent step hands one step of a workflow to an app assistant and gets a structured answer back. The numbers and
 * rules here are the ones the build gate and the app runtime enforce (see the agent step contract), so the editor can
 * say in plain words what the gate would say, before anyone presses Save.
 */
import type {
  AgentAutonomy,
  AgentBrief,
  AgentOnFailure,
  AgentOutputField,
  AgentOutputType,
} from "@/types/ai-features";
import type { WorkflowNodeConfig, WorkflowNodeSerialized } from "@/types/workflow";

export const AGENT_STEP_TYPE = "agent_step";

// ---------------------------------------------------------------------------
// Limits (same ranges the runtime clamps to and the gate checks)
// ---------------------------------------------------------------------------

export type LimitKey = "minConfidence" | "maxActions" | "maxTurns" | "timeoutSec" | "maxTokens";

export interface LimitSpec {
  min: number;
  max: number;
  default: number;
  /** Whole numbers only (everything except the confidence). */
  integer: boolean;
}

export const STEP_LIMITS: Record<LimitKey, LimitSpec> = {
  minConfidence: { min: 0, max: 1, default: 0.85, integer: false },
  maxActions: { min: 1, max: 10, default: 3, integer: true },
  maxTurns: { min: 1, max: 12, default: 6, integer: true },
  timeoutSec: { min: 5, max: 300, default: 60, integer: true },
  maxTokens: { min: 1000, max: 100000, default: 30000, integer: true },
};

/** Keep a typed number inside its range (and whole where it must be). Anything that is not a number becomes the default. */
export function clampLimit(key: LimitKey, value: unknown): number {
  const spec = STEP_LIMITS[key];
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return spec.default;
  const whole = spec.integer ? Math.round(n) : Math.round(n * 100) / 100;
  return Math.min(spec.max, Math.max(spec.min, whole));
}

function limitProblem(key: LimitKey, value: unknown): string | null {
  if (value === undefined || value === null) return null;
  const spec = STEP_LIMITS[key];
  const n = typeof value === "number" ? value : Number(value);
  const ok = Number.isFinite(n) && n >= spec.min && n <= spec.max && (!spec.integer || Number.isInteger(n));
  if (ok) return null;
  const range = `${spec.min.toLocaleString("en-US")} to ${spec.max.toLocaleString("en-US")}`;
  switch (key) {
    case "minConfidence": return "How sure it must be has to be a number from 0 to 1.";
    case "maxActions": return `Changes at one time has to be a whole number from ${range}.`;
    case "maxTurns": return `Turns has to be a whole number from ${range}.`;
    case "timeoutSec": return `Time limit has to be a whole number of seconds from ${range}.`;
    case "maxTokens": return `Size limit has to be a whole number from ${range}.`;
  }
}

// ---------------------------------------------------------------------------
// The three autonomy choices and the failure choices, in plain words
// ---------------------------------------------------------------------------

export const AUTONOMY_CHOICES: { value: AgentAutonomy; label: string; explain: string }[] = [
  {
    value: "suggest",
    label: "Suggest",
    explain: "It only looks things up and suggests. A person or a later step makes any change.",
  },
  {
    value: "limited",
    label: "Limited",
    explain:
      "It may make the changes you list, only when it is confident enough and only a few at a time. Anything else goes to a person.",
  },
  {
    value: "full",
    label: "Full",
    explain: "It may make the changes you list on its own, up to a limit.",
  },
];

export const AUTONOMY_WARNING =
  "Changes made by the assistant happen without anyone looking first. Use this only for things that are easy to undo.";

export const FAILURE_CHOICES: { value: AgentOnFailure; label: string; explain: string }[] = [
  { value: "human", label: "Send to a person", explain: "The step finishes marked as needing a person, so a later decision can route it to someone." },
  { value: "skip", label: "Carry on without it", explain: "The step finishes with an empty answer and the workflow goes on." },
  { value: "fail", label: "Stop the workflow", explain: "The workflow stops with an error." },
];

export const OUTPUT_TYPE_CHOICES: { value: AgentOutputType; label: string }[] = [
  { value: "string", label: "Text" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Yes or no" },
  { value: "enum", label: "Pick one from a list" },
  { value: "array", label: "A list" },
  { value: "object", label: "Several details" },
];

/** What every agent step hands back besides its own answers; later steps read these as {{step.<name>}}. */
export const STANDARD_ENVELOPE: { name: string; type: "boolean" | "number" | "string" | "array"; meaning: string }[] = [
  { name: "needsHuman", type: "boolean", meaning: "The assistant thinks a person should look at this" },
  { name: "confidence", type: "number", meaning: "How sure it is, 0 to 1" },
  { name: "summary", type: "string", meaning: "One plain sentence about what it did" },
  { name: "proposals", type: "array", meaning: "Changes it wanted to make and did not" },
  { name: "actions", type: "array", meaning: "Changes it made (Limited and Full)" },
  { name: "ok", type: "boolean", meaning: "Whether the step finished properly" },
];

// ---------------------------------------------------------------------------
// Answers (output fields)
// ---------------------------------------------------------------------------

export const OUTPUT_NAME_PATTERN = /^[a-z][A-Za-z0-9_]*$/;

export const NAME_RULE_SENTENCE =
  "A name starts with a small letter and uses only letters, numbers and underscores.";

/** Why this answer name cannot be used, or null when it is fine. `others` are the names of the other answers. */
export function outputNameProblem(name: string, others: string[]): string | null {
  const n = (name ?? "").trim();
  if (!n) return "Give this answer a name.";
  if (!OUTPUT_NAME_PATTERN.test(n)) return `"${n}" cannot be a name. ${NAME_RULE_SENTENCE}`;
  if (others.some((o) => o.trim() === n)) return `Two answers are both called "${n}". Each name must be different.`;
  return null;
}

/** A pick-one answer needs at least one allowed value. */
export function enumProblem(f: Pick<AgentOutputField, "name" | "type" | "values">): string | null {
  if (f.type !== "enum" || (f.values ?? []).some((v) => v.trim() !== "")) return null;
  return `The answer "${f.name || "?"}" is a pick-one list, so give it at least one allowed value.`;
}

export function newOutputField(existing: AgentOutputField[]): AgentOutputField {
  let i = existing.length + 1;
  const taken = new Set(existing.map((f) => f.name));
  while (taken.has(`answer${i}`)) i += 1;
  return { name: `answer${i}`, type: "string", description: "", required: true };
}

/** `{{step.result.<name>}}` and `{{step.<standard>}}`, with the type each one has, for the variable picker. */
export function agentStepVariables(
  stepId: string,
  config: Partial<WorkflowNodeConfig> | undefined,
): { path: string; type: "string" | "number" | "boolean" | "array" | "object" | "enum" }[] {
  const out: { path: string; type: "string" | "number" | "boolean" | "array" | "object" | "enum" }[] = [];
  for (const f of asFields(config?.outputFields)) {
    if (!f.name) continue;
    out.push({ path: `${stepId}.result.${f.name}`, type: (f.type as AgentOutputType) || "string" });
  }
  for (const s of STANDARD_ENVELOPE) out.push({ path: `${stepId}.${s.name}`, type: s.type });
  return out;
}

/** The answers list as a clean list of objects, whatever the saved config held. */
export function asFields(raw: unknown): AgentOutputField[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((f): f is Record<string, unknown> => typeof f === "object" && f !== null)
    .map((f) => ({
      name: typeof f.name === "string" ? f.name : "",
      type: (typeof f.type === "string" ? f.type : "string") as AgentOutputType,
      values: Array.isArray(f.values) ? f.values.filter((v): v is string => typeof v === "string") : undefined,
      description: typeof f.description === "string" ? f.description : "",
      required: typeof f.required === "boolean" ? f.required : undefined,
    }));
}

// ---------------------------------------------------------------------------
// Later steps that read this step's answers
// ---------------------------------------------------------------------------

/** Every step that comes after `stepId`, by walking the connections forwards (a loop in the graph cannot hang this). */
export function stepsAfter(edges: Array<{ source: string; target: string }> | undefined, stepId: string): Set<string> {
  const out = new Map<string, string[]>();
  for (const e of Array.isArray(edges) ? edges : []) {
    if (!e || typeof e.source !== "string" || typeof e.target !== "string") continue;
    out.set(e.source, [...(out.get(e.source) ?? []), e.target]);
  }
  const seen = new Set<string>();
  const queue = [...(out.get(stepId) ?? [])];
  while (queue.length) {
    const id = queue.pop()!;
    if (id === stepId || seen.has(id)) continue;
    seen.add(id);
    for (const next of out.get(id) ?? []) queue.push(next);
  }
  return seen;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export interface FieldRead {
  /** The step that reads it. */
  stepId: string;
  stepLabel: string;
  /** The answer it reads (`urgency` in `{{triage.result.urgency}}`). */
  field: string;
}

/**
 * The answers of step `stepId` that later steps read, found by looking for `<stepId>.result.<name>` anywhere in their
 * settings (inside {{ }} or written as a plain variable path). Unreadable settings are skipped, never thrown on.
 */
export function readsOfStep(
  nodes: WorkflowNodeSerialized[],
  edges: Array<{ source: string; target: string }> | undefined,
  stepId: string,
): FieldRead[] {
  const later = stepsAfter(edges, stepId);
  const re = new RegExp(`(?<![A-Za-z0-9_.])${escapeRegExp(stepId)}\\.result\\.([A-Za-z_][A-Za-z0-9_]*)`, "g");
  const reads: FieldRead[] = [];
  for (const n of Array.isArray(nodes) ? nodes : []) {
    if (!n || !later.has(n.id)) continue;
    let text = "";
    try {
      text = JSON.stringify(n.data?.config ?? {});
    } catch {
      continue;
    }
    const seen = new Set<string>();
    for (const m of text.matchAll(re)) {
      if (seen.has(m[1])) continue;
      seen.add(m[1]);
      reads.push({ stepId: n.id, stepLabel: n.data?.label || n.id, field: m[1] });
    }
  }
  return reads;
}

// ---------------------------------------------------------------------------
// The assistant's tools, and which of them change data
// ---------------------------------------------------------------------------

export interface AssistantTool {
  name: string;
  /** "yes": changes data for sure. "maybe": a function or outside tool that could. "no": only reads. */
  changes: "yes" | "maybe" | "no";
  /** The workflow this tool starts, when it starts one. */
  workflowId?: string;
}

interface DefinitionNode {
  data?: { nodeType?: string; label?: string; config?: Record<string, unknown> };
}

/**
 * The tools an assistant's drawing gives it, named as the app names them. Mirrors the platform's own rule for "this
 * tool changes data" (a create, update or delete; any call that is not a plain read; a workflow), and marks a function
 * or outside tool as "maybe" because only its author knows.
 */
export function assistantTools(definition: { nodes?: unknown } | null | undefined): AssistantTool[] {
  const nodes = Array.isArray(definition?.nodes) ? (definition!.nodes as DefinitionNode[]) : [];
  const seen = new Set<string>();
  const out: AssistantTool[] = [];
  for (const n of nodes) {
    if (n?.data?.nodeType !== "tool") continue;
    const cfg = n.data.config ?? {};
    // Same naming as agent-blast's toolNames, so a name picked here is the name the app uses.
    const raw = String(cfg.tool_name || n.data.label || "").trim();
    const base = raw.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60);
    if (!base) continue;
    let name = base;
    for (let i = 2; seen.has(name); i++) name = `${base}_${i}`;
    seen.add(name);
    const type = String(cfg.tool_type || "function").toLowerCase();
    let changes: AssistantTool["changes"] = "no";
    if (type === "data_engine") {
      changes = ["create", "update", "delete"].includes(String(cfg.operation)) ? "yes" : "no";
    } else if (type === "api_call" || type === "external") {
      changes = ["GET", "HEAD"].includes(String(cfg.method || "GET").toUpperCase()) ? "no" : "yes";
    } else if (type === "workflow") {
      changes = "yes";
    } else if (type === "db_query") {
      changes = /^\s*select\b/i.test(String(cfg.query || "")) ? "no" : "maybe";
    } else {
      changes = "maybe";
    }
    out.push({ name, changes, workflowId: type === "workflow" && cfg.workflow_id ? String(cfg.workflow_id) : undefined });
  }
  return out;
}

export function isWorkflowOnly(agentId: string | undefined | null): boolean {
  return typeof agentId === "string" && agentId.startsWith("wf_");
}

// ---------------------------------------------------------------------------
// What is wrong with the step (the gate's sentences, ahead of the gate)
// ---------------------------------------------------------------------------

export interface StepIssue {
  /** "error": the build would refuse it. "note": worth knowing, not a refusal. */
  level: "error" | "note";
  text: string;
  /** Where in the panel it belongs. */
  area: "assistant" | "task" | "answers" | "autonomy" | "limits" | "failure";
  /** Set when the problem is about one answer (counting from 0): the panel shows it under that answer, not in the list. */
  row?: number;
}

export function agentStepIssues(args: {
  config: Partial<WorkflowNodeConfig> | undefined;
  stepId: string;
  nodes: WorkflowNodeSerialized[];
  edges?: Array<{ source: string; target: string }>;
  /** The assistant's tools, once they have been read (undefined = not known yet or could not be read). */
  tools?: AssistantTool[] | null;
  /** This workflow's id, to spot an assistant that could start the workflow it works in. */
  workflowId?: string;
  /** The ids of the project's assistants, once the list has loaded (undefined = not known, so say nothing about it). */
  assistantIds?: string[];
}): StepIssue[] {
  const { config, stepId, nodes, edges, tools, workflowId, assistantIds } = args;
  const c = (config ?? {}) as Partial<WorkflowNodeConfig>;
  const issues: StepIssue[] = [];
  const err = (area: StepIssue["area"], text: string, row?: number) => issues.push({ level: "error", area, text, row });
  const note = (area: StepIssue["area"], text: string) => issues.push({ level: "note", area, text });

  // The assistant
  const hasAgent = typeof c.agentId === "string" && c.agentId.trim() !== "";
  if (hasAgent && assistantIds && !assistantIds.includes(c.agentId as string)) {
    err("assistant", `The assistant "${c.agentId}" cannot be found in this project. Pick another one, or create one for this step.`);
  }
  if (!hasAgent) {
    if (c.agentBrief && typeof c.agentBrief === "object") {
      note("assistant", "This step's assistant has not been made yet. It is made when the app is built, or you can make it now.");
    } else {
      err("assistant", "Pick an assistant for this step, or create one for it.");
    }
  }

  // The task
  if (!(typeof c.task === "string" && c.task.trim())) {
    err("task", "Say what the assistant should do this time.");
  }

  // The answers
  const fields = asFields(c.outputFields);
  if (fields.length === 0) {
    err("answers", "Add at least one answer for the assistant to hand back. Later steps can only read what is listed here.");
  }
  fields.forEach((f, i) => {
    const others = fields.filter((_, j) => j !== i).map((o) => o.name);
    const p = outputNameProblem(f.name, others);
    // A duplicate would be reported once per copy; say it once.
    if (p && !(p.startsWith("Two answers") && fields.findIndex((o) => o.name.trim() === f.name.trim()) !== i)) {
      err("answers", p, i);
    }
    const e = enumProblem(f);
    if (e) err("answers", e, i);
  });

  // Later steps reading an answer that is not there
  const have = new Set(fields.map((f) => f.name.trim()));
  const flagged = new Set<string>();
  for (const r of readsOfStep(nodes, edges, stepId)) {
    if (have.has(r.field)) continue;
    const key = `${r.stepId}|${r.field}`;
    if (flagged.has(key)) continue;
    flagged.add(key);
    err(
      "answers",
      `The step "${r.stepLabel}" reads "{{${stepId}.result.${r.field}}}", but this step does not hand back an answer called "${r.field}".`,
    );
  }

  // Autonomy
  const autonomy = (c.autonomy ?? "suggest") as string;
  if (!["suggest", "limited", "full"].includes(autonomy)) {
    err("autonomy", "Choose how much the assistant may do by itself: Suggest, Limited or Full.");
  }
  const allowed = Array.isArray(c.allowedWriteTools) ? c.allowedWriteTools.filter((t) => typeof t === "string" && t.trim()) : [];
  if ((autonomy === "limited" || autonomy === "full") && allowed.length === 0) {
    const label = autonomy === "limited" ? "Limited" : "Full";
    err("autonomy", `You chose ${label}, but listed no changes the assistant may make. Pick at least one, or switch to Suggest.`);
  }
  if (tools) {
    const names = new Set(tools.map((t) => t.name));
    for (const t of allowed) {
      if (!names.has(t)) err("autonomy", `"${t}" is not one of this assistant's tools.`);
    }
    const heldBack = tools.filter((t) => t.changes === "yes" && !allowed.includes(t.name)).map((t) => t.name);
    if (heldBack.length > 0) {
      note(
        "autonomy",
        autonomy === "suggest"
          ? `This assistant has tools that change data (${heldBack.join(", ")}). In this step they only ever become suggestions.`
          : `This assistant also has tools that change data and are not on your list (${heldBack.join(", ")}). Those only ever become suggestions.`,
      );
    }
    if (workflowId && tools.some((t) => t.workflowId === workflowId)) {
      err("assistant", "This assistant can start the very workflow it works in, which would make it loop. Pick a different assistant, or take that tool off it.");
    }
  }

  // Limits
  for (const key of ["maxActions", "maxTurns", "timeoutSec", "maxTokens"] as const) {
    const p = limitProblem(key, c[key]);
    if (p) err("limits", p);
  }
  if (autonomy === "limited") {
    const p = limitProblem("minConfidence", c.minConfidence);
    if (p) err("autonomy", p);
  }

  // What to do when it cannot finish
  if (c.onFailure !== undefined && !["human", "skip", "fail"].includes(String(c.onFailure))) {
    err("failure", "Choose what happens when the assistant cannot finish: send to a person, carry on, or stop.");
  }

  return issues;
}

// ---------------------------------------------------------------------------
// The "create an assistant for this step" brief
// ---------------------------------------------------------------------------

/** A multi-line box of names, one per line (commas work too), blanks and repeats dropped. */
export function parseNameList(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of String(text ?? "").split(/[\n,]/)) {
    const t = part.trim();
    if (t && !seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  }
  return out;
}

export interface BriefDraft {
  purpose: string;
  reads: string;
  mayChange: { tool: string; why: string }[];
}

export const BRIEF_PURPOSE_MAX = 600;

/** Why the brief cannot be sent yet, in a sentence, or null. */
export function briefProblem(draft: BriefDraft): string | null {
  if (!draft.purpose.trim()) return "Say what the assistant should do.";
  if (draft.purpose.length > BRIEF_PURPOSE_MAX) return `Keep it under ${BRIEF_PURPOSE_MAX} characters.`;
  if (parseNameList(draft.reads).length === 0) return "List what it may read, one per line.";
  const half = draft.mayChange.find((m) => (m.tool.trim() === "") !== (m.why.trim() === ""));
  if (half) return "Each change it may make needs both the tool name and a reason.";
  return null;
}

export function toBrief(draft: BriefDraft): AgentBrief {
  const mayChange = draft.mayChange
    .filter((m) => m.tool.trim() && m.why.trim())
    .map((m) => ({ tool: m.tool.trim(), why: m.why.trim() }));
  return {
    purpose: draft.purpose.trim(),
    reads: parseNameList(draft.reads),
    ...(mayChange.length ? { mayChange } : {}),
  };
}

export function draftFromBrief(brief: AgentBrief | undefined | null): BriefDraft {
  return {
    purpose: brief?.purpose ?? "",
    reads: Array.isArray(brief?.reads) ? brief!.reads.join("\n") : "",
    mayChange: Array.isArray(brief?.mayChange) ? brief!.mayChange!.map((m) => ({ tool: m.tool, why: m.why })) : [],
  };
}

/** What a from-brief answer says: the id, plus any warnings, as plain sentences. */
export interface FromBriefAnswer {
  agentId: string;
  name?: string;
  warnings: string[];
}

export function readFromBrief(raw: unknown): FromBriefAnswer | null {
  const r = raw as { agentId?: unknown; name?: unknown; warnings?: unknown } | null;
  if (!r || typeof r.agentId !== "string" || !r.agentId) return null;
  const warnings = Array.isArray(r.warnings)
    ? r.warnings.map((w) => (typeof w === "string" ? w : (w as { message?: string })?.message ?? "")).filter(Boolean)
    : [];
  return { agentId: r.agentId, name: typeof r.name === "string" ? r.name : undefined, warnings };
}

// ---------------------------------------------------------------------------
// Small readers shared by the canvas badge, the instruction builder and the panel
// ---------------------------------------------------------------------------

export const AUTONOMY_LABEL: Record<AgentAutonomy, string> = { suggest: "Suggest", limited: "Limited", full: "Full" };

export function autonomyOf(config: Partial<WorkflowNodeConfig> | undefined): AgentAutonomy {
  const a = config?.autonomy;
  return a === "limited" || a === "full" ? a : "suggest";
}
