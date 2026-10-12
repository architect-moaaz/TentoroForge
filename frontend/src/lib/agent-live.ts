/**
 * The builder's live run: turning the app's event stream into steps a person can read, and spotting inputs that
 * are probably wrong. No React, no network: the reducer and the checks are plain functions, tested on their own.
 *
 * The app streams (see backend/templates/runtime/api-agent/debug-route.ts): `debug_start` (the prompt, the tools,
 * who it runs as), then per model call `text` words, a `model_call` (time, tokens, what it asked for), and for each
 * tool a `tool_call` (the exact input), maybe a `tool_faked` (it changes data, so it was not run), and a
 * `tool_result` (the real data). Every event carries `t`, the milliseconds since the run began.
 */

export type LiveEvent = { type: string; t?: number; [key: string]: any };

export interface ToolInfo {
  name: string;
  kind: string;
  description: string;
  confirm: boolean;
  /** Known to change data (so a debug run does not run it). */
  changes: boolean;
  inputSchema: { type?: string; properties?: Record<string, any>; required?: string[]; additionalProperties?: boolean };
}

export interface AgentInfo {
  id: string;
  name: string;
  model: string | null;
  systemPrompt: string;
  maxTurns: number;
  tools: ToolInfo[];
}

export interface InputProblem {
  code: "unknown_tool" | "missing" | "unexpected" | "wrong_type" | "unseen_id";
  field?: string;
  message: string;
}

export type ModelStep = {
  kind: "model";
  n: number;
  t: number;
  ms: number;
  inputTokens: number;
  outputTokens: number;
  messages: number;
  toolsRequested: string[];
  /** What the model said while it was working (before a tool, or its final answer). */
  said: string;
};

export type ToolStep = {
  kind: "tool";
  id: string;
  tool: string;
  t: number;
  input: unknown;
  status: "running" | "ok" | "failed" | "held" | "not_run";
  problems: InputProblem[];
  result?: unknown;
  error?: string;
  chars?: number;
  cut?: boolean;
  ms?: number;
  /** Why a tool that changes data was not run. */
  notRunReason?: string;
};

export type Step = ModelStep | ToolStep;

export interface LiveRun {
  status: "idle" | "running" | "done" | "blocked" | "error";
  agent?: AgentInfo;
  user?: { id: string; name: string; email: string | null; role: string | null };
  allowChanges: boolean;
  draft: boolean;
  /** Warnings from compiling the draft. */
  notes: string[];
  steps: Step[];
  answer: string;
  /** Text that arrived since the last model call; it belongs to the next one. */
  pending: string;
  conversationId?: string;
  blocked?: string;
  error?: string;
  /** Everything the agent has been shown in this conversation (people's messages and what tools returned): an id
   *  that appears nowhere in it did not come from the data. Kept across messages of one session. */
  seen: string;
  totals: { ms: number; inputTokens: number; outputTokens: number; modelCalls: number; toolCalls: number };
}

export const emptyRun = (): LiveRun => ({
  status: "idle",
  allowChanges: false,
  draft: false,
  notes: [],
  steps: [],
  answer: "",
  pending: "",
  seen: "",
  totals: { ms: 0, inputTokens: 0, outputTokens: 0, modelCalls: 0, toolCalls: 0 },
});

/** A new message in the same conversation: the trace starts fresh, what was seen is kept (and the new message is
 *  part of it). */
export function beginRun(prev: LiveRun, message: string): LiveRun {
  return { ...emptyRun(), status: "running", agent: prev.agent, user: prev.user, allowChanges: prev.allowChanges, draft: prev.draft, conversationId: prev.conversationId, seen: `${prev.seen}\n${message}` };
}

// ── input checks ──────────────────────────────────────────────────────────

const ID_KEY = /(^id$|Id$|_id$)/;

const typeOf = (v: unknown): string => (Array.isArray(v) ? "array" : v === null ? "null" : typeof v);

const matchesType = (want: unknown, v: unknown): boolean => {
  const types = Array.isArray(want) ? (want as string[]) : [want as string];
  return types.some((t) => (t === "integer" ? Number.isInteger(v) : t === "number" ? typeof v === "number" : t === "object" ? typeof v === "object" && v !== null && !Array.isArray(v) : typeof v === t || (t === "array" && Array.isArray(v)) || (t === "null" && v === null)));
};

/** Ids the model wrote that look like a record's id, wherever they sit in the input. */
function idValues(input: unknown, path = ""): Array<{ field: string; value: string }> {
  if (Array.isArray(input)) return input.flatMap((v, i) => idValues(v, `${path}[${i}]`));
  if (!input || typeof input !== "object") return [];
  const out: Array<{ field: string; value: string }> = [];
  for (const [k, v] of Object.entries(input as Record<string, unknown>)) {
    const here = path ? `${path}.${k}` : k;
    if (typeof v === "string" && v && ID_KEY.test(k)) out.push({ field: here, value: v });
    else if (v && typeof v === "object") out.push(...idValues(v, here));
  }
  return out;
}

/**
 * What looks wrong with the input a tool was called with. Cheap, local, and wrong only in the safe direction (a
 * warning to look at, never a block).
 */
export function checkInput(tool: ToolInfo | undefined, tool_name: string, input: unknown, seen: string): InputProblem[] {
  if (!tool) return [{ code: "unknown_tool", message: `This agent has no tool called "${tool_name}".` }];
  const problems: InputProblem[] = [];
  const obj = input && typeof input === "object" && !Array.isArray(input) ? (input as Record<string, unknown>) : {};
  const schema = tool.inputSchema ?? {};
  const props = schema.properties ?? {};

  for (const key of schema.required ?? []) {
    const v = obj[key];
    if (v === undefined || v === null || v === "") problems.push({ code: "missing", field: key, message: `Missing "${key}", which this tool needs.` });
  }
  for (const [key, v] of Object.entries(obj)) {
    const spec = props[key];
    if (!spec) {
      if (schema.additionalProperties === false) problems.push({ code: "unexpected", field: key, message: `"${key}" is not something this tool accepts.` });
      continue;
    }
    if (spec.type && v !== undefined && v !== null && !matchesType(spec.type, v)) {
      problems.push({ code: "wrong_type", field: key, message: `"${key}" should be ${Array.isArray(spec.type) ? spec.type.join(" or ") : spec.type}, but it is ${typeOf(v)}.` });
    }
  }
  for (const { field, value } of idValues(input)) {
    if (!seen.includes(value)) {
      problems.push({
        code: "unseen_id",
        field,
        message: `"${value}" did not come from anything the agent was shown (your messages or an earlier result), so it may have been made up.`,
      });
    }
  }
  return problems;
}

// ── the reducer ───────────────────────────────────────────────────────────

const lastModel = (steps: Step[]): ModelStep | undefined => [...steps].reverse().find((s): s is ModelStep => s.kind === "model");

/** Hand text that has no model call after it (a run that stopped early) to the last one. */
const flush = (run: LiveRun): LiveRun => {
  if (!run.pending) return run;
  const m = lastModel(run.steps);
  if (!m) return run;
  return { ...run, steps: run.steps.map((s) => (s === m ? { ...m, said: m.said + run.pending } : s)), pending: "" };
};

/** Replace the step with this tool call id. */
const withTool = (run: LiveRun, id: string, fn: (s: ToolStep) => ToolStep): LiveRun => ({
  ...run,
  steps: run.steps.map((s) => (s.kind === "tool" && s.id === id ? fn(s) : s)),
});

export function applyEvent(run: LiveRun, e: LiveEvent): LiveRun {
  const t = typeof e.t === "number" ? e.t : 0;
  switch (e.type) {
    case "platform_note":
      return { ...run, notes: [...run.notes, ...((e.warnings as string[]) ?? [])] };

    case "debug_start":
      return { ...run, agent: e.agent as AgentInfo, user: e.user, allowChanges: !!e.allowChanges, draft: !!e.draft };

    case "text": {
      const c = String(e.content ?? "");
      return { ...run, pending: run.pending + c, answer: run.answer + c };
    }

    case "model_call": {
      const step: ModelStep = {
        kind: "model",
        n: e.n,
        t,
        ms: e.ms,
        inputTokens: e.inputTokens,
        outputTokens: e.outputTokens,
        messages: e.messages,
        toolsRequested: e.toolsRequested ?? [],
        said: run.pending.trim(),
      };
      return {
        ...run,
        pending: "",
        steps: [...run.steps, step],
        totals: {
          ...run.totals,
          modelCalls: run.totals.modelCalls + 1,
          inputTokens: run.totals.inputTokens + (e.inputTokens || 0),
          outputTokens: run.totals.outputTokens + (e.outputTokens || 0),
        },
      };
    }

    case "tool_call": {
      const info = run.agent?.tools.find((x) => x.name === e.tool);
      const step: ToolStep = {
        kind: "tool",
        id: e.id,
        tool: e.tool,
        t,
        input: e.input,
        status: "running",
        problems: checkInput(info, e.tool, e.input, run.seen),
      };
      return { ...run, steps: [...run.steps, step], totals: { ...run.totals, toolCalls: run.totals.toolCalls + 1 } };
    }

    case "tool_faked": {
      // Arrives right after its tool_call and before its tool_result: the newest running step of that tool.
      const target = [...run.steps].reverse().find((s): s is ToolStep => s.kind === "tool" && s.tool === e.tool && s.status === "running");
      return target ? withTool(run, target.id, (s) => ({ ...s, notRunReason: String(e.reason ?? "it changes data") })) : run;
    }

    case "tool_result": {
      const held = !!e.result && typeof e.result === "object" && (e.result as { held?: unknown }).held === true;
      const next = withTool(run, e.id, (s) => ({
        ...s,
        status: !e.ok ? "failed" : held ? "held" : s.notRunReason ? "not_run" : "ok",
        result: e.result,
        error: e.error,
        chars: e.chars,
        cut: !!e.cut,
        ms: Math.max(0, t - s.t),
      }));
      // What a tool returned is now something the agent has seen.
      const text = typeof e.result === "string" ? e.result : safeJson(e.result);
      return { ...next, seen: `${next.seen}\n${text}` };
    }

    case "blocked":
      return { ...flush(run), status: "blocked", blocked: String(e.reason ?? "Blocked.") };

    case "error":
      return { ...flush(run), status: "error", error: String(e.message ?? "Something went wrong.") };

    case "done":
      return {
        ...flush(run),
        status: run.status === "running" ? "done" : run.status,
        conversationId: e.conversationId ?? run.conversationId,
        totals: { ...run.totals, ms: t },
      };

    default:
      return run;
  }
}

function safeJson(v: unknown): string {
  try {
    return JSON.stringify(v) ?? "";
  } catch {
    return String(v);
  }
}

// ── what is shown ─────────────────────────────────────────────────────────

/** The model reads a whole result in the turn it asked for it; later turns replay only this many characters. */
export const REPLAY_CHARS = 3000;

/** Rows of a result, when it is a list of records (as the app's data tools return). */
export function rowsOf(result: unknown): Array<Record<string, unknown>> | null {
  const list = Array.isArray(result) ? result : result && typeof result === "object" ? ((result as any).data ?? (result as any).rows ?? (result as any).items) : null;
  if (!Array.isArray(list) || list.length === 0) return null;
  return list.every((r) => r && typeof r === "object" && !Array.isArray(r)) ? (list as Array<Record<string, unknown>>) : null;
}

/** Split a chunk of the stream into whole events; what is left over waits for the next chunk. */
export function parseEvents(buffer: string): { events: LiveEvent[]; rest: string } {
  const events: LiveEvent[] = [];
  let rest = buffer;
  let cut: number;
  while ((cut = rest.indexOf("\n\n")) >= 0) {
    const raw = rest.slice(0, cut);
    rest = rest.slice(cut + 2);
    const line = raw.split("\n").find((l) => l.startsWith("data:"));
    if (!line) continue;
    try {
      events.push(JSON.parse(line.slice(5).trim()));
    } catch {
      /* a half line: skipped */
    }
  }
  return { events, rest };
}
