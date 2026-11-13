/**
 * Helpers for watching the app's real chats live. Forge runtime — do not remove.
 *
 * The builder (in TTF) can watch a running development app's chats as they happen (see watch.ts and
 * api-agent/debug-route.ts). The pieces here are the small, pure ones: comparing the platform's secret without leaking
 * it, putting a tool's result on the wire (cut if huge, and said to be), and reporting each request a tool makes in
 * the app so the builder sees the real method, route and status behind it.
 */
import type { ToolIO } from "./tools";

/** What a watched chat says beyond the chat's own events. */
export type DebugEvent =
  | { type: "model_call"; n: number; ms: number; inputTokens: number; outputTokens: number; messages: number; toolsRequested: string[] }
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

// ── the secret ────────────────────────────────────────────────────────────

/** Constant-time comparison, so the secret cannot be guessed a character at a time. */
export function sameSecret(a: string, b: string): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// ── what goes to the builder ──────────────────────────────────────────────

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
    callMcp: (serverId, tool, args) => timed({ kind: "mcp", label: `${serverId}/${tool}`, body: clipBody(args) }, () => io.callMcp(serverId, tool, args)),
    runAi: (action, config, input, user) => timed({ kind: "ai", label: action }, () => io.runAi(action, config, input, user)),
  };
}
