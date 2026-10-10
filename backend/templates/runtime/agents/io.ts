/**
 * The real model and the real tool back-ends. Forge runtime — do not remove.
 *
 * Everything the loop was tested against a fake of is here: the Anthropic call,
 * the app's own routes, the workflow engine, the MCP pool, the AI presets and the
 * per-agent tool modules. Imports are dynamic so a part the app doesn't use (no
 * MCP server, no workflows) is never loaded.
 */
import type { FetchInit, ToolIO } from "./tools";
import { ToolError, createToolRunner, RateLimiter } from "./tools";
import type { AgentDeps, ModelBlock, ModelRequest, ModelResult, ToolContext } from "./types";

// ── the model ─────────────────────────────────────────────────────────────

async function secret(key: string): Promise<string | undefined> {
  const { getSecret } = await import("@/lib/integrations/resolver");
  return getSecret("anthropic", key);
}

export const DEFAULT_MODEL = "claude-sonnet-4-6";

/** Is a model call possible at all? The Test console asks before it promises one. */
export async function modelConfigured(): Promise<boolean> {
  return !!(await secret("ANTHROPIC_API_KEY"));
}

export async function callModel(req: ModelRequest, onText: (chunk: string) => void): Promise<ModelResult> {
  const apiKey = await secret("ANTHROPIC_API_KEY");
  if (!apiKey) {
    // Production (or FORGE_AI_STRICT) must not pretend: a canned answer to a real
    // customer is worse than an error. Dev boots green with a labelled mock.
    if (process.env.NODE_ENV === "production" || process.env.FORGE_AI_STRICT === "1") {
      throw new Error("AI is not configured — set ANTHROPIC_API_KEY (env or /settings/integrations).");
    }
    const last = [...req.messages].reverse().find((m) => m.role === "user");
    const said = typeof last?.content === "string" ? last.content : "";
    const mock = `[mock reply — set ANTHROPIC_API_KEY for a real one] You said: ${said.slice(0, 200)}`;
    onText(mock);
    return { content: [{ type: "text", text: mock }], usage: { inputTokens: 0, outputTokens: 0 } };
  }

  const model = req.model || (await secret("FORGE_AI_MODEL")) || process.env.ANTHROPIC_MODEL || DEFAULT_MODEL;
  const mod: any = await import("@anthropic-ai/sdk");
  const Anthropic = mod.default ?? mod.Anthropic ?? mod;
  const client = new Anthropic({ apiKey });

  const stream = client.messages.stream({
    model,
    max_tokens: req.maxTokens,
    ...(req.temperature != null ? { temperature: req.temperature } : {}),
    system: req.system,
    messages: req.messages,
    ...(req.tools.length ? { tools: req.tools } : {}),
  });
  stream.on("text", (t: string) => onText(t));
  const final = await stream.finalMessage();
  return {
    content: (final.content ?? []) as ModelBlock[],
    usage: { inputTokens: final.usage?.input_tokens ?? 0, outputTokens: final.usage?.output_tokens ?? 0 },
  };
}

// ── the app's own routes ──────────────────────────────────────────────────

function internalBase(ctx: ToolContext): string {
  // FORGE_INTERNAL_URL pins it for deployments where the request's own origin is
  // not reachable from the server (a proxy that rewrites Host).
  return (process.env.FORGE_INTERNAL_URL || ctx.origin).replace(/\/$/, "");
}

async function fetchInternal(path: string, init: FetchInit, ctx: ToolContext): Promise<unknown> {
  const url = new URL(internalBase(ctx) + path);
  for (const [k, v] of Object.entries(init.query ?? {})) {
    if (v == null || v === "") continue;
    url.searchParams.set(k, typeof v === "object" ? JSON.stringify(v) : String(v));
  }
  const res = await fetch(url, {
    method: init.method,
    headers: {
      accept: "application/json",
      ...(init.body !== undefined ? { "content-type": "application/json" } : {}),
      // The person's own session: the route decides what they may see and do.
      cookie: ctx.cookie,
    },
    ...(init.body !== undefined ? { body: JSON.stringify(init.body) } : {}),
  });
  const raw = await res.text();
  let body: any = raw;
  try { body = raw ? JSON.parse(raw) : null; } catch { /* leave as text */ }
  if (!res.ok) {
    const msg = body?.error?.message ?? (typeof body?.error === "string" ? body.error : null) ?? `${res.status} ${res.statusText}`;
    if (res.status === 403) {
      // A bare "Forbidden" made the model retry or guess. Say what it means, and what to do.
      throw new ToolError(
        `Not allowed: this app does not let the signed-in person's role ${init.method} ${path.split("?")[0]} directly. ` +
        "Do not retry. Tell the person plainly that you cannot do this for them here.",
        "auth",
      );
    }
    throw new ToolError(String(msg), res.status === 401 ? "auth" : "failed");
  }
  return body;
}

// ── the rest ──────────────────────────────────────────────────────────────

export const toolIO: ToolIO = {
  fetchInternal,

  async triggerWorkflow(id, input, user) {
    const { initializeRuntime } = await import("@/lib/runtime-loader");
    const { triggerWorkflow } = await import("@/lib/workflows");
    await initializeRuntime();
    const r: any = await triggerWorkflow(id, input, user ?? undefined);
    if (r?.status === "failed") throw new ToolError(r.error || `${id} failed.`, "failed");
    return { status: r?.status, output: r?.output ?? {} };
  },

  async callMcp(serverId, tool, args) {
    const { callMcpTool } = await import("@/lib/integrations/mcpClientPool");
    const r = await callMcpTool(serverId, tool, args);
    const text = r.content.filter((p) => p.type === "text").map((p) => p.text ?? "").join("\n");
    if (r.isError) throw new ToolError(text || `${tool} failed.`, "failed");
    // Servers answer in text; most of it is JSON.
    try { return JSON.parse(text); } catch { return text || r.content; }
  },

  async runAi(action, config, input, user) {
    const ai: any = await import("@/lib/workflows/ai");
    const ctx = { input, variables: input, log: [], user: user ?? undefined };
    const text = String(input.text ?? input.input ?? input.prompt ?? "");
    switch (action) {
      case "identify_product":
        return ai.aiIdentifyProduct(
          { ...config, image_file_id: input.image_file_id ?? input.file_id ?? input.imageId ?? input.image },
          ctx,
        );
      case "classify":
        return ai.aiClassify({ ...config, aiInput: input.input ?? input.text ?? config.aiInput }, ctx);
      case "extract":
        return ai.aiExtract({ ...config, aiInput: input.input ?? input.text ?? input.file_id ?? config.aiInput }, ctx);
      case "generate":
        return ai.aiGenerate({ ...config, aiPrompt: config.aiPrompt ?? text, aiInput: input }, ctx);
    }
  },

  async runFunction(handler, input, ctx) {
    const reg: any = await import("@/agents/registry");
    const load = reg.TOOL_HANDLERS?.[handler];
    if (!load) throw new ToolError(`No tool module "${handler}" is registered.`, "unavailable");
    const mod = await load();
    return mod.default(input, { user: ctx.user, cookie: ctx.cookie, origin: ctx.origin });
  },
};

const limiter = new RateLimiter();

/** The dependencies a chat request runs with. */
export async function realDeps(store: AgentDeps["store"]): Promise<AgentDeps> {
  let evalExpression: AgentDeps["evalExpression"];
  try {
    const feel: any = await import("@/lib/feel-lite");
    evalExpression = (expr, scope) => feel.evaluateExpression(expr, scope);
  } catch {
    /* no FEEL-lite in this app: output rules are skipped */
  }
  return { callModel, runTool: createToolRunner(toolIO, limiter), store, evalExpression };
}
