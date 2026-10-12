/**
 * The builder's live run — helpers. Forge runtime — do not remove.
 *
 * A debug run is the app's REAL chat loop (the same `runAgent` its customers use) with a few differences, all
 * made here so the loop itself stays untouched:
 *   - it runs as a person the builder picks, with that person's own session, so the data is what they would see;
 *   - nothing is saved to the app's tables: the conversation lives in memory for a while, so a follow-up works;
 *   - usage limits and handoffs are out of it (a test must not use up anyone's allowance or page a real person);
 *   - a tool that is known to change data is NOT run unless the builder switched "run changes for real" on:
 *     the assistant gets a clear "not run" answer and carries on, so the rest of the run can still be watched;
 *   - every model call is timed and counted, so the builder can see where time and tokens go.
 *
 * The route (api-agent/debug-route.ts) is the only way in, and it only answers in development with the platform's
 * secret. Pure helpers here, tested on their own.
 */
import { changesData } from "./confirm";
import { memoryStore } from "./memory";
import type { ToolIO } from "./tools";
import type { AgentDeps, AgentRuntimeConfig, AgentToolSpec, ConversationStore } from "./types";

/** What a debug run says beyond the normal events. Every event also carries `t`, ms since the run began. */
export type DebugEvent =
  | { type: "debug_start"; agent: Record<string, unknown>; user: Record<string, unknown>; allowChanges: boolean; draft: boolean }
  | { type: "model_call"; n: number; ms: number; inputTokens: number; outputTokens: number; messages: number; toolsRequested: string[] }
  | { type: "tool_faked"; tool: string; reason: string }
  | AppCall;

/** One thing a tool did in the app: a request to one of its routes (with the real method, path and status), a
 *  workflow, an MCP tool or an AI action. Arrives between the tool's call and its result. */
export interface AppCall {
  type: "app_call";
  kind: "request" | "workflow" | "mcp" | "ai";
  /** What was called: the path, the workflow id, `server/tool`, or the AI action. */
  label: string;
  method?: string;
  query?: Record<string, unknown>;
  /** What was sent, for a call that changes something. */
  body?: unknown;
  status?: number;
  ms: number;
  ok: boolean;
  error?: string;
}

// ── conversations kept in memory ──────────────────────────────────────────

const SESSION_MINUTES = 60;
const MAX_SESSIONS = 50;
const sessions = new Map<string, { store: ConversationStore; at: number }>();

/** The conversation store for one debug session: the same one for the same id, so a follow-up (or a "yes" to a held
 *  change) finds what came before. Forgotten after an hour, and never more than MAX_SESSIONS at once. */
export function sessionStore(id: string, now: number = Date.now()): ConversationStore {
  for (const [k, v] of sessions) if (now - v.at > SESSION_MINUTES * 60_000) sessions.delete(k);
  let s = sessions.get(id);
  if (!s) {
    if (sessions.size >= MAX_SESSIONS) {
      const oldest = [...sessions.entries()].sort((a, b) => a[1].at - b[1].at)[0];
      if (oldest) sessions.delete(oldest[0]);
    }
    s = { store: memoryStore(), at: now };
    sessions.set(id, s);
  }
  s.at = now;
  return s.store;
}

// ── the secret ────────────────────────────────────────────────────────────

/** Constant-time comparison, so the secret cannot be guessed a character at a time. */
export function sameSecret(a: string, b: string): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// ── what the builder is shown ─────────────────────────────────────────────

/** The agent as it will run: the prompt exactly as the model gets it, and each tool with what it accepts. */
export function describeAgent(config: AgentRuntimeConfig): Record<string, unknown> {
  return {
    id: config.id,
    name: config.name,
    model: config.model?.name ?? null,
    systemPrompt: config.systemPrompt,
    maxTurns: config.maxTurns,
    tools: config.tools.map((t) => ({
      name: t.name,
      kind: t.kind,
      description: t.description,
      confirm: !!t.confirm,
      changes: t.confirm || t.kind === "handoff" || changesData(t),
      inputSchema: t.inputSchema,
    })),
  };
}

/** Results can be large; the screen gets what fits, and is told when it was cut. */
export const MAX_RESULT_WIRE_CHARS = 60_000;

export function wireResult(result: unknown): { result: unknown; chars: number; cut: boolean } {
  let text: string;
  try {
    text = JSON.stringify(result ?? null);
  } catch {
    return { result: String(result), chars: 0, cut: false };
  }
  if (text.length <= MAX_RESULT_WIRE_CHARS) return { result, chars: text.length, cut: false };
  return { result: `${text.slice(0, MAX_RESULT_WIRE_CHARS)}…`, chars: text.length, cut: true };
}

// ── what the tools did in the app ─────────────────────────────────────────

const clipBody = (body: unknown): unknown => {
  try {
    const text = JSON.stringify(body);
    return text && text.length > 2000 ? `${text.slice(0, 2000)}…` : body;
  } catch {
    return String(body);
  }
};

/** `io` with every call it makes reported to `send`, so the builder sees the real requests behind a tool: the
 *  method, the route, the status and how long it took. Results pass through untouched. */
export function instrumentIO(io: ToolIO, send: (e: DebugEvent) => void): ToolIO {
  const timed = async <T>(base: Omit<AppCall, "ms" | "ok" | "type" | "error">, fn: (note: (call: Partial<AppCall>) => void) => Promise<T>): Promise<T> => {
    const started = Date.now();
    let extra: Partial<AppCall> = {};
    try {
      const out = await fn((c) => (extra = { ...extra, ...c }));
      send({ type: "app_call", ...base, ...extra, ms: Date.now() - started, ok: true });
      return out;
    } catch (e) {
      send({ type: "app_call", ...base, ...extra, ms: Date.now() - started, ok: false, error: e instanceof Error ? e.message : String(e) });
      throw e;
    }
  };

  return {
    ...io,
    fetchInternal: (path, init, ctx) =>
      timed(
        {
          kind: "request",
          label: path,
          method: init.method,
          ...(init.query && Object.keys(init.query).length ? { query: init.query } : {}),
          ...(init.method !== "GET" && init.body !== undefined ? { body: clipBody(init.body) } : {}),
        },
        (note) => io.fetchInternal(path, { ...init, onResponse: (status) => { init.onResponse?.(status); note({ status }); } }, ctx),
      ),
    triggerWorkflow: (id, input, user) => timed({ kind: "workflow", label: id, body: clipBody(input) }, () => io.triggerWorkflow(id, input, user)),
    callMcp: (serverId, tool, args) => timed({ kind: "mcp", label: `${serverId}/${tool}`, body: clipBody(args) }, () => io.callMcp(serverId, tool, args)),
    runAi: (action, config, input, user) => timed({ kind: "ai", label: action }, () => io.runAi(action, config, input, user)),
  };
}

// ── the loop's dependencies, instrumented ─────────────────────────────────

const refused = (spec: AgentToolSpec): string =>
  spec.kind === "handoff"
    ? "it would hand the conversation to a person and notify them"
    : "it changes data";

/**
 * `base` with what a debug run changes (see the header). `send` receives the extra events.
 */
export function debugDeps(base: AgentDeps, send: (e: DebugEvent) => void, opts: { allowChanges: boolean }): AgentDeps {
  let n = 0;
  return {
    ...base,
    usage: undefined,
    handoffs: undefined,

    async callModel(req, onText) {
      const started = Date.now();
      const out = await base.callModel(req, onText);
      send({
        type: "model_call",
        n: ++n,
        ms: Date.now() - started,
        inputTokens: out.usage.inputTokens,
        outputTokens: out.usage.outputTokens,
        messages: req.messages.length,
        toolsRequested: out.content.filter((b) => b.type === "tool_use").map((b) => (b as { name: string }).name),
      });
      return out;
    },

    async runTool(spec, input, ctx, scope) {
      if (!opts.allowChanges && (spec.kind === "handoff" || spec.confirm || changesData(spec))) {
        send({ type: "tool_faked", tool: spec.name, reason: refused(spec) });
        return {
          ok: true,
          debug_note: `Not run: this is a debug run and ${refused(spec)}. The builder can switch on "run changes for real" to let it run.`,
          would_have_run_with: input,
        };
      }
      return base.runTool(spec, input, ctx, scope);
    },
  };
}
