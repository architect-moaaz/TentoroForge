/**
 * Agent tools — what the model may call, and how each call is carried out.
 * Forge runtime — do not remove.
 *
 * Every kind of tool reaches the app THROUGH THE APP: data and api tools call the
 * app's own routes with the signed-in person's session cookie, so the data
 * engine's role checks, ownership scope and masking apply to the agent exactly as
 * they do to that person in the browser. (A header that names the acting user —
 * `X-Agent-User-Id` — would let anyone act as anyone; the cookie cannot be forged.)
 *
 * The pure parts — rate limiting, argument mapping, response filtering, the
 * dispatch — live here with the I/O behind `ToolIO`, so they are tested without
 * a server.
 */
import type {
  AgentToolSpec,
  AgentUser,
  ModelToolDef,
  ToolContext,
} from "./types";

// ── what the model sees ───────────────────────────────────────────────────

export function toModelTools(specs: AgentToolSpec[]): ModelToolDef[] {
  return specs.map((s) => ({
    name: s.name,
    description: s.description || s.name,
    input_schema: s.inputSchema ?? { type: "object", properties: {} },
  }));
}

// ── rate limiting ─────────────────────────────────────────────────────────

const UNIT_MS: Record<string, number> = {
  s: 1000, sec: 1000, second: 1000,
  m: 60_000, min: 60_000, minute: 60_000,
  h: 3_600_000, hour: 3_600_000,
  d: 86_400_000, day: 86_400_000,
};

/** "10/min" → {limit: 10, windowMs: 60000}. Anything unreadable → no limit. */
export function parseRate(rate: string | undefined): { limit: number; windowMs: number } | null {
  if (!rate) return null;
  const m = String(rate).trim().toLowerCase().match(/^(\d+)\s*\/\s*([a-z]+)$/);
  if (!m) return null;
  const windowMs = UNIT_MS[m[2]];
  const limit = Number(m[1]);
  return windowMs && limit > 0 ? { limit, windowMs } : null;
}

/** A sliding window per key, in this process. Serverless instances each keep their
 *  own window — a floor against a runaway loop, not a billing meter. */
export class RateLimiter {
  private hits = new Map<string, number[]>();
  private now: () => number;
  constructor(now: () => number = Date.now) {
    this.now = now;
  }

  /** True when the call may go ahead (and is counted). */
  take(key: string, rate: string | undefined): boolean {
    const parsed = parseRate(rate);
    if (!parsed) return true;
    const t = this.now();
    const live = (this.hits.get(key) ?? []).filter((x) => t - x < parsed.windowMs);
    if (live.length >= parsed.limit) {
      this.hits.set(key, live);
      return false;
    }
    live.push(t);
    this.hits.set(key, live);
    return true;
  }
}

// ── argument mapping ──────────────────────────────────────────────────────

function readPath(scope: unknown, path: string): unknown {
  let cur: any = scope;
  for (const part of path.split(".")) {
    if (cur == null) return undefined;
    cur = cur[part];
  }
  return cur;
}

const WHOLE = /^\{\{\s*([^}]+?)\s*\}\}$/;
const EACH = /\{\{\s*([^}]+?)\s*\}\}/g;

/** `{{brand}}` on its own keeps the value's type; embedded in text it is spliced in.
 *  Names resolve against `scope` (tool results by tool name) with the model's own
 *  input under `input.` and, failing that, at the top level. */
export function resolveTemplate(value: unknown, scope: Record<string, unknown>, input: Record<string, unknown>): unknown {
  if (typeof value !== "string") return value;
  const look = (p: string) => {
    const hit = readPath({ ...input, ...scope, input }, p);
    return hit;
  };
  const whole = value.match(WHOLE);
  if (whole) return look(whole[1]);
  return value.replace(EACH, (_m, p: string) => {
    const v = look(p);
    return v == null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
  });
}

/** The arguments an MCP tool is called with: each mapped argument resolved, then
 *  whatever else the model supplied. */
export function mapArgs(
  mapping: Record<string, string> | undefined,
  input: Record<string, unknown>,
  scope: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  // The model's own inputs that a mapping already consumed (`{{input.term}}`,
  // `{{term}}`) are not passed on as well — the server would be handed an
  // argument it never declared.
  const consumed = new Set<string>();
  for (const [k, v] of Object.entries(mapping ?? {})) {
    for (const m of String(v).matchAll(EACH)) {
      const head = m[1].replace(/^input\./, "").split(".")[0];
      if (head in input) consumed.add(head);
    }
    const resolved = resolveTemplate(v, scope, input);
    if (resolved !== undefined && resolved !== "") out[k] = resolved;
  }
  for (const [k, v] of Object.entries(input)) {
    if (!(k in out) && !consumed.has(k)) out[k] = v;
  }
  return out;
}

// ── response filtering ────────────────────────────────────────────────────

function pick(obj: unknown, keys: string[]): unknown {
  if (obj == null || typeof obj !== "object" || Array.isArray(obj)) return obj;
  const out: Record<string, unknown> = {};
  for (const k of keys) if (k in (obj as Record<string, unknown>)) out[k] = (obj as any)[k];
  return out;
}

/** Keep only the listed keys — of an array's elements, of a `{data: [...]}` list
 *  envelope's rows (the data route's shape), or of a single object. */
export function filterResponse(result: unknown, keys: string[] | undefined): unknown {
  if (!keys || keys.length === 0) return result;
  if (Array.isArray(result)) return result.map((r) => pick(r, keys));
  if (result && typeof result === "object" && Array.isArray((result as any).data)) {
    return { ...(result as object), data: (result as any).data.map((r: unknown) => pick(r, keys)) };
  }
  return pick(result, keys);
}

// ── credentials never leave through a tool ───────────────────────────────

const CREDENTIAL_WORDS = new Set([
  "password", "passwd", "passcode", "secret", "salt", "hash", "apikey", "credential", "credentials", "token",
]);
// Counters named for tokens, not credentials made of them.
const TOKEN_COUNTER = /^tokens$|^tokens?(count|used|usage|total|limit)$/;

/** Is this key one the application authenticates with? Split into words so
 *  `passwordHash`, `password_hash` and `api_key` are caught and `hashtag` is not. */
export function isCredentialKey(key: string): boolean {
  const flat = key.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (TOKEN_COUNTER.test(flat)) return false;
  const words = key.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  if (words.some((w) => CREDENTIAL_WORDS.has(w))) return true;
  return words.some((w, i) => w === "api" && words[i + 1] === "key") || flat === "apikey";
}

/**
 * What a tool returns goes to the model and is saved with the conversation, so the
 * floor sits here and not in the tool: a `data` tool over `users` is handed the row
 * the app stores, hash and all, by a route that only the page's own columns were
 * ever expected to reach. Nothing the app authenticates with is passed on — the
 * same rule the CSV export holds itself to.
 */
export function redactCredentials(value: unknown, depth = 0): unknown {
  if (value == null || depth > 8) return value;
  if (Array.isArray(value)) return value.map((v) => redactCredentials(v, depth + 1));
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (isCredentialKey(k)) continue;
      out[k] = redactCredentials(v, depth + 1);
    }
    return out;
  }
  return value;
}

// ── dispatch ──────────────────────────────────────────────────────────────

export interface FetchInit {
  method: string;
  query?: Record<string, unknown>;
  body?: unknown;
}

export interface ToolIO {
  fetchInternal(path: string, init: FetchInit, ctx: ToolContext): Promise<unknown>;
  triggerWorkflow(id: string, input: Record<string, unknown>, user: AgentUser | null): Promise<unknown>;
  callMcp(serverId: string, tool: string, args: Record<string, unknown>): Promise<unknown>;
  runAi(
    action: NonNullable<AgentToolSpec["aiAction"]>,
    config: Record<string, unknown>,
    input: Record<string, unknown>,
    user: AgentUser | null,
  ): Promise<unknown>;
  runFunction(handler: string, input: Record<string, unknown>, ctx: ToolContext): Promise<unknown>;
}

export type ToolErrorCode = "auth" | "rate_limit" | "invalid" | "unavailable" | "failed";

export class ToolError extends Error {
  code: ToolErrorCode;
  constructor(message: string, code: ToolErrorCode = "failed") {
    super(message);
    this.name = "ToolError";
    this.code = code;
  }
}

/** A path inside THIS app and not the agent's own door — an agent that can call
 *  /api/agent/chat can call itself without end. */
export function assertInternalPath(path: string): string {
  if (!path.startsWith("/api/") || path.includes("..") || path.includes("//") || /^\/api\/agent(\/|$)/.test(path)) {
    throw new ToolError(`"${path}" is not a route this tool may call.`, "invalid");
  }
  return path;
}

function fillPathParams(endpoint: string, input: Record<string, unknown>): { path: string; rest: Record<string, unknown> } {
  const rest = { ...input };
  const path = endpoint.replace(/:([A-Za-z_][A-Za-z0-9_]*)/g, (_m, name: string) => {
    const v = rest[name];
    if (v == null || v === "") throw new ToolError(`Missing "${name}" for ${endpoint}.`, "invalid");
    delete rest[name];
    return encodeURIComponent(String(v));
  });
  return { path, rest };
}

async function runData(spec: AgentToolSpec, input: Record<string, unknown>, ctx: ToolContext, io: ToolIO): Promise<unknown> {
  const entity = spec.entity;
  if (!entity) throw new ToolError(`${spec.name} names no entity.`, "invalid");
  const base = `/api/data/${encodeURIComponent(entity)}`;
  const id = input.id != null ? encodeURIComponent(String(input.id)) : "";
  switch (spec.operation ?? "list") {
    case "list": {
      const { filters, ...flat } = input as { filters?: Record<string, unknown> } & Record<string, unknown>;
      return io.fetchInternal(base, { method: "GET", query: { ...(filters ?? {}), ...flat } }, ctx);
    }
    case "get":
      if (!id) throw new ToolError("An id is required.", "invalid");
      return io.fetchInternal(`${base}/${id}`, { method: "GET" }, ctx);
    case "create":
      return io.fetchInternal(base, { method: "POST", body: input.data ?? input }, ctx);
    case "update":
      if (!id) throw new ToolError("An id is required.", "invalid");
      return io.fetchInternal(`${base}/${id}`, { method: "PUT", body: input.data ?? {} }, ctx);
    case "delete":
      if (!id) throw new ToolError("An id is required.", "invalid");
      return io.fetchInternal(`${base}/${id}`, { method: "DELETE" }, ctx);
  }
}

/**
 * The function the runtime calls for every tool use: authorisation, rate limit,
 * dispatch, response filter. Throws `ToolError` — the loop reports it to the model
 * as an error result so it can say so, instead of ending the conversation.
 */
export function createToolRunner(io: ToolIO, limiter: RateLimiter = new RateLimiter()) {
  return async function runTool(
    spec: AgentToolSpec,
    input: Record<string, unknown>,
    ctx: ToolContext,
    scope: Record<string, unknown>,
  ): Promise<unknown> {
    if (spec.requireAuth !== false && !ctx.user) {
      throw new ToolError("Sign in to use this.", "auth");
    }
    if (!limiter.take(`${ctx.user?.id ?? "anon"}:${spec.name}`, spec.rateLimit)) {
      throw new ToolError(`${spec.name} was called too often — try again shortly.`, "rate_limit");
    }

    let result: unknown;
    switch (spec.kind) {
      case "data":
        result = await runData(spec, input, ctx, io);
        break;
      case "api": {
        if (!spec.endpoint) throw new ToolError(`${spec.name} names no endpoint.`, "invalid");
        const { path, rest } = fillPathParams(spec.endpoint, { ...(spec.defaultParams ?? {}), ...input });
        const method = (spec.method ?? "GET").toUpperCase();
        result = await io.fetchInternal(
          assertInternalPath(path),
          method === "GET" || method === "DELETE" ? { method, query: rest } : { method, body: rest },
          ctx,
        );
        break;
      }
      case "workflow":
        if (!spec.workflowId) throw new ToolError(`${spec.name} names no workflow.`, "invalid");
        result = await io.triggerWorkflow(spec.workflowId, input, ctx.user);
        break;
      case "mcp":
        if (!spec.mcpServerId || !spec.mcpToolName) {
          throw new ToolError(`${spec.name} is not connected to an MCP server.`, "unavailable");
        }
        result = await io.callMcp(spec.mcpServerId, spec.mcpToolName, mapArgs(spec.argsMapping, input, scope));
        break;
      case "ai_action":
        if (!spec.aiAction) throw new ToolError(`${spec.name} names no AI action.`, "invalid");
        result = await io.runAi(spec.aiAction, spec.aiConfig ?? {}, input, ctx.user);
        break;
      case "function":
        if (!spec.handler) {
          throw new ToolError(
            `${spec.name} has no implementation yet — it was described but no code was supplied.`,
            "unavailable",
          );
        }
        result = await io.runFunction(spec.handler, input, ctx);
        break;
      default:
        throw new ToolError(`Unknown tool kind for ${spec.name}.`, "invalid");
    }
    return redactCredentials(filterResponse(result, spec.responseFilter));
  };
}
