/**
 * Who an assistant step acts as, and what that identity can touch. Forge runtime — do not remove.
 *
 * THE DESIGN (read this before changing anything here)
 *
 * A chat tool reaches the app's data over HTTP with the signed-in person's session cookie, so the app's own checks
 * decide what the assistant may do. An assistant step has no person and no cookie. The tempting fix is a "service
 * bearer" that routes would accept; that is a key that opens routes, and a key can leak, be replayed or be used from
 * outside. This file does the opposite: NOTHING is minted and NO ROUTE ACCEPTS ANYTHING NEW. The step runs its tools
 * inside the app's own process, through the same data layer the routes call (data-engine.ts: validation, business
 * rules, ownership and row-access, masking, the audit trail), as an explicit actor object:
 *
 *   workflow:<workflowId>   restricted to the grants below, valid for ONE run of ONE step, and not a thing that
 *                           exists on the wire at all, so there is nothing to forge, replay, expire or steal.
 *
 * What the actor can do is exactly its GRANTS: the assistant's own tools, by name, and nothing else. While the model
 * runs, the actor holds the READ tools only: a data-changing tool is never granted then, so even a bug in the step's
 * interception could not change data. After a valid result the gates (workflow-run.ts) decide which proposals to
 * carry out, and only for those tool names is a second actor made (`makeActor(..., granted)`). Every grant is a key
 * (`data:pets:list`, `workflow:book_appointment`, `mcp:server:tool`, `ai:classify`, `function:name`); the back-ends
 * below refuse anything whose key is not held, a second line behind the tool-name check.
 *
 * To the data engine the actor is a role named `workflow` with no id. The engine therefore treats it like any other
 * role: an ownership rule or a row-access rule that does not name that role returns it NO rows (it fails closed, as
 * the engine does for a visitor), the audit trail records the write as made via `workflow:<id>` in run <runId>, and a
 * sensitive column is masked unless its readers include `workflow`. The role gates of the HTTP route (ENTITY_ACCESS)
 * are not consulted: they are written for people's roles, and no one holds the role `workflow`. The grants are the
 * permission here. A tool that calls a page route (`api`) or hands over to a person (`handoff`) has no in-process form
 * and is refused with a plain sentence.
 *
 * Every tool call is logged (one line, no values): who, which run, which tool, how long, whether it worked, and
 * whether it was refused. A write is also on the audit trail through `via` and `runId`.
 */
import { changesData } from "./confirm";
import { ToolError, type DataCall, type ToolIO } from "./tools";
import type { AgentToolSpec, AgentUser, ToolContext } from "./types";

export type RunTool = (
  spec: AgentToolSpec,
  input: Record<string, unknown>,
  ctx: ToolContext,
  scope: Record<string, unknown>,
) => Promise<unknown>;

/** What the data layer must offer: the data engine's own functions, so a test can hand in a fake. */
export interface DataLayer {
  /** Registers the entities (the engine's initialiser). */
  ready(): Promise<void>;
  query(entity: string, opts: Record<string, unknown>, ctx: Record<string, unknown>): Promise<unknown>;
  findById(entity: string, id: string, ctx: Record<string, unknown>): Promise<unknown>;
  create(entity: string, data: Record<string, unknown>, ctx: Record<string, unknown>): Promise<{ data: unknown }>;
  update(entity: string, id: string, data: Record<string, unknown>, ctx: Record<string, unknown>): Promise<{ data: unknown }>;
  remove(entity: string, id: string, ctx: Record<string, unknown>): Promise<{ data: unknown }>;
  /** An append-only entity can be written once and never changed or removed. */
  isAppendOnly?(entity: string): boolean;
}

export interface WorkflowActor {
  readonly kind: "workflow";
  /** `workflow:<workflowId>` — what the logs, the rate limits and the turn record call it. */
  readonly id: string;
  readonly workflowId: string;
  readonly stepId: string;
  readonly runId: string;
  readonly agentId: string;
  /** The tools this actor may run, by name. */
  readonly grants: ReadonlySet<string>;
  /** What those tools reach (see grantKey). */
  readonly keys: ReadonlySet<string>;
}

/** What one tool reaches, or null for a tool that has no in-process form (a page route, a handoff). */
export function grantKey(spec: AgentToolSpec): string | null {
  switch (spec.kind) {
    case "data":
      return spec.entity ? `data:${spec.entity.toLowerCase()}:${spec.operation ?? "list"}` : null;
    case "workflow":
      return spec.workflowId ? `workflow:${spec.workflowId}` : null;
    case "mcp":
      return spec.mcpServerId && spec.mcpToolName ? `mcp:${spec.mcpServerId}:${spec.mcpToolName}` : null;
    case "ai_action":
      return spec.aiAction ? `ai:${spec.aiAction}` : null;
    case "function":
      return spec.handler ? `function:${spec.handler}` : null;
    default:
      return null;
  }
}

/**
 * The actor for one step of one run, holding exactly the named tools of the assistant. A name the assistant does not
 * have is simply not granted (nothing is invented), and a tool with no in-process form is never granted.
 */
export function makeActor(p: {
  workflowId: string;
  stepId: string;
  runId: string;
  agentId: string;
  tools: AgentToolSpec[];
  granted: string[];
}): WorkflowActor {
  const want = new Set(p.granted);
  const grants = new Set<string>();
  const keys = new Set<string>();
  for (const t of p.tools) {
    if (!want.has(t.name)) continue;
    const key = grantKey(t);
    if (!key) continue;
    grants.add(t.name);
    keys.add(key);
  }
  return Object.freeze({
    kind: "workflow" as const,
    id: `workflow:${p.workflowId}`,
    workflowId: p.workflowId,
    stepId: p.stepId,
    runId: p.runId,
    agentId: p.agentId,
    grants,
    keys,
  });
}

/** The actor as the tool runner sees a person: it needs an id (its rate-limit key) and a role. */
export function actorUser(actor: WorkflowActor): AgentUser {
  return { id: actor.id, role: "workflow" };
}

/** What the engines are handed: a role with no id (so no row is "its own") — see the design note above. */
export function engineUser(): AgentUser {
  return { id: "", role: "workflow" };
}

// ── the guard in front of the tool runner ─────────────────────────────────

export interface StepLogEntry {
  event: "agent_step_tool";
  actor: string;
  workflowId: string;
  stepId: string;
  runId: string;
  agentId: string;
  tool: string;
  kind: string;
  changes: boolean;
  ok: boolean;
  refused: boolean;
  ms: number;
  error?: string;
}

export const logToConsole = (entry: StepLogEntry): void => {
  try {
    console.info("[agent-step]", JSON.stringify(entry));
  } catch {
    /* a broken logger is not the step's problem */
  }
};

const clip = (s: string, n = 200) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function refuse(message: string): never {
  throw new ToolError(message, "auth");
}

/**
 * `inner` (the app's normal tool runner, over this actor's own back-ends) behind three checks that run BEFORE it:
 * the person asking is this actor and no one else, the tool is the assistant's own (the very object from its
 * definition, not a look-alike) and the actor holds it. Every call, allowed or not, leaves one log line.
 */
export function guardTools(actor: WorkflowActor, tools: AgentToolSpec[], inner: RunTool, log: (e: StepLogEntry) => void = logToConsole): RunTool {
  const own = new Map(tools.map((t) => [t.name, t]));
  return async (spec, input, ctx, scope) => {
    const started = Date.now();
    const entry = (ok: boolean, refused: boolean, error?: string): StepLogEntry => ({
      event: "agent_step_tool",
      actor: actor.id,
      workflowId: actor.workflowId,
      stepId: actor.stepId,
      runId: actor.runId,
      agentId: actor.agentId,
      tool: spec.name,
      kind: spec.kind,
      changes: changesData(spec),
      ok,
      refused,
      ms: Date.now() - started,
      ...(error ? { error: clip(error) } : {}),
    });
    try {
      if (ctx.user?.id !== actor.id) refuse("This step may only act as its own workflow, not as anyone else.");
      if (own.get(spec.name) !== spec) refuse(`${spec.name} is not one of this assistant's tools.`);
      if (!actor.grants.has(spec.name)) {
        refuse(
          changesData(spec)
            ? `${spec.name} changes data, and this step may not run it. It is recorded as a proposal instead.`
            : `${spec.name} is not one of the tools this step may use.`,
        );
      }
      const out = await inner(spec, input, ctx, scope);
      log(entry(true, false));
      return out;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      log(entry(false, e instanceof ToolError && (e.code === "auth" || e.code === "unavailable"), msg));
      throw e;
    }
  };
}

// ── the actor's own back-ends ─────────────────────────────────────────────

const SPECIAL_QUERY_KEYS = new Set(["search", "page", "limit", "sort", "order", "unmask"]);

/** A list request as the data route reads its URL: the named options, every other value a filter, `unmask` never. */
export function listOptions(query: Record<string, unknown> | undefined): Record<string, unknown> {
  const q = query ?? {};
  const filters: Record<string, string> = {};
  for (const [k, v] of Object.entries(q)) {
    if (v == null || v === "" || SPECIAL_QUERY_KEYS.has(k)) continue;
    filters[k] = typeof v === "object" ? JSON.stringify(v) : String(v);
  }
  const whole = (v: unknown, d: number) => Number.parseInt(String(v ?? ""), 10) || d;
  return {
    search: q.search ? String(q.search) : undefined,
    filters,
    sort: q.sort ? String(q.sort) : undefined,
    order: q.order === "asc" ? "asc" : "desc",
    page: Math.max(whole(q.page, 1), 1),
    limit: Math.min(Math.max(whole(q.limit, 50), 1), 200),
  };
}

/** What the engine said, in the plain words a tool error carries (the route's own mapping, without the HTTP). */
function toToolError(e: unknown): ToolError {
  if (e instanceof ToolError) return e;
  const err = e as { name?: string; code?: string; message?: string } | null;
  const message = String(err?.message ?? e);
  if (err?.name === "ValidationError") return new ToolError(message, "invalid");
  if (err?.name === "NotFoundError" || err?.code === "22P02") return new ToolError("No record with that id.", "failed");
  if (err?.code === "23505") return new ToolError("A record with this value already exists.", "failed");
  if (err?.code === "23502") return new ToolError(`Required field missing: ${message.match(/column "(\w+)"/)?.[1] ?? "unknown"}.`, "invalid");
  if (/^Unknown entity/.test(message)) return new ToolError(message, "failed");
  return new ToolError(clip(message, 300), "failed");
}

/** A data result as the route would have sent it: plain JSON (a Date is its text), so the credential filter can read it. */
const asJson = (v: unknown): unknown => (v === undefined ? null : JSON.parse(JSON.stringify(v)));

/**
 * The tool back-ends of one actor. `base` carries the parts that need no person (workflows, MCP, AI presets, tool
 * modules); the data goes straight to the data layer; a route call and a handoff are refused.
 */
export function workflowToolIO(
  actor: WorkflowActor,
  base: Pick<ToolIO, "triggerWorkflow" | "callMcp" | "runAi" | "runFunction">,
  layer: () => Promise<DataLayer>,
): ToolIO {
  const need = (key: string, what: string) => {
    if (!actor.keys.has(key)) refuse(`${what} is not something this step may do.`);
  };
  return {
    async fetchInternal() {
      throw new ToolError(
        "This tool calls a page of the app that needs a signed-in person, so a workflow step cannot use it.",
        "unavailable",
      );
    },

    async requestHandoff() {
      throw new ToolError(
        "A workflow step cannot hand over to a person. Set needsHuman in your result instead.",
        "unavailable",
      );
    },

    async data(call: DataCall) {
      need(`data:${call.entity.toLowerCase()}:${call.operation}`, `${call.operation} on ${call.entity}`);
      const data = await layer();
      if ((call.operation === "update" || call.operation === "delete") && data.isAppendOnly?.(call.entity)) {
        throw new ToolError(`${call.entity} is append-only: rows cannot be updated or deleted.`, "failed");
      }
      try {
        await data.ready();
        const ctx = {
          user: engineUser(),
          via: `workflow:${actor.workflowId}`,
          runId: actor.runId,
          ...(call.operation === "list" || call.operation === "get"
            ? {}
            : { reason: `Made by an assistant step (${actor.stepId}) of workflow ${actor.workflowId}.` }),
        };
        switch (call.operation) {
          case "list":
            return asJson(await data.query(call.entity, listOptions(call.query), ctx));
          case "get":
            return asJson(await data.findById(call.entity, String(call.id), ctx));
          case "create":
            return asJson((await data.create(call.entity, (call.body ?? {}) as Record<string, unknown>, ctx)).data);
          case "update":
            return asJson((await data.update(call.entity, String(call.id), (call.body ?? {}) as Record<string, unknown>, ctx)).data);
          case "delete":
            return asJson((await data.remove(call.entity, String(call.id), ctx)).data);
        }
      } catch (e) {
        throw toToolError(e);
      }
    },

    async triggerWorkflow(id, input) {
      need(`workflow:${id}`, `Running the workflow ${id}`);
      return base.triggerWorkflow(id, input, engineUser());
    },

    async callMcp(serverId, tool, args) {
      need(`mcp:${serverId}:${tool}`, `The tool ${tool} of ${serverId}`);
      return base.callMcp(serverId, tool, args);
    },

    async runAi(action, config, input) {
      need(`ai:${action}`, `The AI action ${action}`);
      return base.runAi(action, config, input, engineUser());
    },

    async runFunction(handler, input, ctx) {
      need(`function:${handler}`, `The tool module ${handler}`);
      return base.runFunction(handler, input, { ...ctx, user: actorUser(actor), cookie: "" });
    },
  };
}
