/**
 * Turning the app's event stream for one chat into steps a person can read, and spotting inputs that are probably
 * wrong. No React, no network: the reducer and the checks are plain functions, tested on their own.
 *
 * The app streams (see backend/templates/runtime/agents/watch.ts): `run_start` (who wrote what), the runtime's
 * `phase`s, then per model call `model_start`, `text` words and a `model_call` (time, tokens, what it asked for), and
 * for each tool a `tool_call` (the exact input), the `app_call`s it made (the real requests) and a `tool_result` (the
 * real data). Every event carries `t`, the milliseconds since the chat began.
 */

export type LiveEvent = { type: string; t?: number; [key: string]: any };

/** A tool as the agent's drawing defines it: what its input may hold. */
export interface ToolInfo {
  name: string;
  kind?: string;
  description?: string;
  confirm?: boolean;
  inputSchema: { type?: string; properties?: Record<string, any>; required?: string[]; additionalProperties?: boolean };
}

export interface InputProblem {
  code: "missing" | "unexpected" | "wrong_type" | "unseen_id";
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
  /** The model has been called and has not answered yet (the live view). `messages` is what it was given. */
  running?: boolean;
  /** How many tools it was offered, and how long its instructions are (known as the call starts). */
  tools?: number;
  systemChars?: number;
  /** Why the call failed, if it did. */
  failed?: string;
};

/** A step the runtime took that is not a model or tool call: checking the message, loading memory, checking the
 *  answer, or finding the conversation is with a person. */
export interface Phase {
  phase: "input_check" | "memory" | "with_person" | "output_check";
  t: number;
  ok?: boolean;
  reason?: string;
  messages?: number;
  summarised?: boolean;
  ref?: string;
}

/** What a tool did in the app: a request to one of its routes (real method, path and status), a workflow, ... */
export interface AppCall {
  kind: "request" | "workflow" | "mcp" | "ai";
  label: string;
  method?: string;
  query?: Record<string, unknown>;
  body?: unknown;
  status?: number;
  ms: number;
  ok: boolean;
  error?: string;
}

export type ToolStep = {
  kind: "tool";
  id: string;
  tool: string;
  t: number;
  input: unknown;
  status: "running" | "ok" | "failed" | "held";
  problems: InputProblem[];
  result?: unknown;
  error?: string;
  chars?: number;
  cut?: boolean;
  ms?: number;
  /** What the tool did in the app while it ran. */
  calls: AppCall[];
};

export type Step = ModelStep | ToolStep;

export interface LiveRun {
  status: "idle" | "running" | "done" | "blocked" | "error";
  /** The tools as drawn, so an input can be checked against what each accepts. Absent: only the id check runs. */
  tools?: ToolInfo[];
  user?: { id: string; name: string | null; email: string | null; role: string | null };
  /** What the person typed. */
  message?: string;
  /** The runtime's own steps, in order. */
  phases: Phase[];
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
  phases: [],
  steps: [],
  answer: "",
  pending: "",
  seen: "",
  totals: { ms: 0, inputTokens: 0, outputTokens: 0, modelCalls: 0, toolCalls: 0 },
});

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
export function checkInput(tool: ToolInfo | undefined, input: unknown, seen: string): InputProblem[] {
  const problems: InputProblem[] = [];
  // What the tool accepts is only known when its definition is: without it, only the id check below can run.
  if (tool) {
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
    case "text": {
      const c = String(e.content ?? "");
      return { ...run, pending: run.pending + c, answer: run.answer + c };
    }

    case "run_start":
      return { ...run, user: e.user, message: e.message, seen: `${run.seen}\n${e.message ?? ""}`, conversationId: e.conversationId ?? run.conversationId };

    case "phase": {
      const { type: _t, t: _at, ...rest } = e;
      return { ...run, phases: [...run.phases, { ...(rest as Omit<Phase, "t">), t }] };
    }

    case "model_start": {
      const step: ModelStep = {
        kind: "model", n: e.n, t, ms: 0, inputTokens: 0, outputTokens: 0, messages: e.messages, toolsRequested: [], said: "",
        running: true, tools: e.tools, systemChars: e.systemChars,
      };
      return { ...run, steps: [...run.steps, step] };
    }

    case "model_failed": {
      const target = [...run.steps].reverse().find((s): s is ModelStep => s.kind === "model" && s.n === e.n);
      const steps = target ? run.steps.map((s) => (s === target ? { ...target, running: false, ms: e.ms, failed: String(e.error ?? "failed") } : s)) : run.steps;
      return { ...run, steps };
    }

    case "model_call": {
      const open = [...run.steps].reverse().find((s): s is ModelStep => s.kind === "model" && s.n === e.n && !!s.running);
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
        ...(open ? { tools: open.tools, systemChars: open.systemChars } : {}),
      };
      return {
        ...run,
        pending: "",
        // The call announced itself when it began: its card is finished, not added again.
        steps: open ? run.steps.map((s) => (s === open ? step : s)) : [...run.steps, step],
        totals: {
          ...run.totals,
          modelCalls: run.totals.modelCalls + 1,
          inputTokens: run.totals.inputTokens + (e.inputTokens || 0),
          outputTokens: run.totals.outputTokens + (e.outputTokens || 0),
        },
      };
    }

    case "tool_call": {
      const info = run.tools?.find((x) => x.name === e.tool);
      const step: ToolStep = {
        kind: "tool",
        id: e.id,
        tool: e.tool,
        t,
        input: e.input,
        status: "running",
        problems: checkInput(info, e.input, run.seen),
        calls: [],
      };
      return { ...run, steps: [...run.steps, step], totals: { ...run.totals, toolCalls: run.totals.toolCalls + 1 } };
    }

    case "app_call": {
      // Arrives while its tool is still running: the newest running step.
      const target = [...run.steps].reverse().find((s): s is ToolStep => s.kind === "tool" && s.status === "running");
      const { type: _t, t: _at, ...call } = e;
      return target ? withTool(run, target.id, (s) => ({ ...s, calls: [...s.calls, call as AppCall] })) : run;
    }

    case "tool_result": {
      const held = !!e.result && typeof e.result === "object" && (e.result as { held?: unknown }).held === true;
      const next = withTool(run, e.id, (s) => ({
        ...s,
        status: !e.ok ? "failed" : held ? "held" : "ok",
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
