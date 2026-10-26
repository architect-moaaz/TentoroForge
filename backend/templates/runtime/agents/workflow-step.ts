/**
 * The assistant step (`agent_step`) of the workflow engine: the real handler and what connects it to the app.
 * Forge runtime — do not remove.
 *
 * The run itself (two phases, limits, the answer's check) is workflow-run.ts; who it acts as and what that can touch is
 * workflow-actor.ts. This file is the wiring: it finds the assistant the step names, resolves the step's `{{refs}}`
 * from the workflow's variables, builds the tool back-ends for the service actor (in-process, no cookie, no route),
 * lets a builder watching the app live see the run like a chat, records the turn, and shapes onFailure.
 *
 * Registered by `registerAgentStepAction()`, which the engine calls from `registerDefaultActions` through
 * src/lib/workflows/agent-step.ts (the hook that the install puts over the stub).
 *
 * RESUME: the engine remembers a finished step and replays its answer when a run resumes after an approval further
 * down, so the model is not asked again and the changes it made are not made twice.
 */
import { agentStepSample } from "../workflows/dry-run-stand-in";
import { resolveString, resolveValue } from "../workflows/ai";
import { registerActionHandler } from "../workflows/engine";
import type { NodeConfig, WorkflowExecutionContext } from "../workflows/types";
import { changesData } from "./confirm";
import { instrumentIO } from "./debug";
import { modelConfigured, realDeps, toolIO } from "./io";
import { RateLimiter, createToolRunner } from "./tools";
import type { AgentRuntimeConfig, ConversationStore } from "./types";
import { feedEvent, newRunId, observeDeps, publish, watching, type WatchEvent } from "./watch";
import { guardTools, logToConsole, makeActor, workflowToolIO, type DataLayer } from "./workflow-actor";
import { conversationIdOf, failedOutcome, runAgentStep, settingsOf, type StepDeps } from "./workflow-run";

/** One window of tool calls per workflow and tool, in this process (the tool's own rateLimit, as in chat). */
const limiter = new RateLimiter();

/** A step is stateless: nothing is kept between runs, so the store the shared dependencies ask for holds nothing. */
const statelessStore: ConversationStore = {
  async getConversation() { return null; },
  async createConversation() { throw new Error("An assistant step keeps no conversation."); },
  async listMessages() { return []; },
  async saveMessage() {},
  async setSummary() {},
};

let layer: Promise<DataLayer> | null = null;

/** The app's own data layer, loaded once: the same functions the data route calls. */
function dataLayer(): Promise<DataLayer> {
  return (layer ??= (async (): Promise<DataLayer> => {
    const engine: any = await import("@/lib/data-engine");
    const init: any = await import("@/lib/data-init");
    const appendOnly: any = await import("@/lib/append-only-entities");
    return {
      ready: () => init.ensureDataEngineInitialized(),
      query: (entity, opts, ctx) => engine.query(entity, opts, ctx),
      findById: (entity, id, ctx) => engine.findById(entity, id, ctx),
      create: (entity, data, ctx) => engine.create(entity, data, ctx),
      update: (entity, id, data, ctx) => engine.update(entity, id, data, ctx),
      remove: (entity, id, ctx) => engine.remove(entity, id, ctx),
      isAppendOnly: (entity) => !!appendOnly.isAppendOnly?.(entity),
    };
  })().catch((e) => {
    layer = null;
    throw e;
  }));
}

/** The workflow run this step belongs to: the engine's own id when it has one, else one made for this run. */
function runIdOf(ctx: WorkflowExecutionContext): string {
  const c = ctx as any;
  return String(c.runId || c.workflowInstanceId || (c.__agentStepRunId ??= `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`));
}

export async function agentStepAction(config: NodeConfig, ctx: WorkflowExecutionContext): Promise<Record<string, unknown>> {
  const cfg = config as Record<string, any>;
  // A dry run never calls a model or a tool: the sample answer stands in (workflows/dry-run-stand-in.ts).
  if ((ctx as any).dryRun === true) return agentStepSample(cfg);

  const vars = (ctx.variables ?? {}) as Record<string, unknown>;
  const workflowId = String(cfg.__workflowId ?? (ctx as any).workflowId ?? "workflow");
  const stepId = String(cfg.__nodeId ?? (ctx as any).currentNodeId ?? "step");
  const workflowRunId = runIdOf(ctx);

  const input: Record<string, unknown> = {};
  for (const [name, ref] of Object.entries((cfg.input && typeof cfg.input === "object" ? cfg.input : {}) as Record<string, unknown>)) {
    input[name] = resolveValue(ref, vars);
  }
  const step = settingsOf(cfg, { task: resolveString(cfg.task, vars), input });

  // What can be wrong before any run exists is the builder's, said in words, and follows onFailure like any failure.
  const finish = (outcome: ReturnType<typeof failedOutcome>): Record<string, unknown> => {
    if (outcome.failed && step.onFailure === "fail") throw new Error(outcome.envelope.error);
    return outcome.envelope as unknown as Record<string, unknown>;
  };
  const agentId = typeof cfg.agentId === "string" ? cfg.agentId.trim() : "";
  if (!agentId) return finish(failedOutcome(step.onFailure, "setup", "This step has no assistant yet. Choose or create the assistant it should use."));
  const registry: any = await import("@/agents/registry");
  const agent = ((registry.AGENTS ?? []) as AgentRuntimeConfig[]).find((a) => a.id === agentId);
  if (!agent) return finish(failedOutcome(step.onFailure, "setup", `The assistant "${agentId}" is not installed in this app. Apply the assistant, then run the workflow again.`));

  const base = await realDeps(statelessStore, toolIO);
  // A builder watching this development app live sees the step like a chat; nothing is kept unless someone watches.
  const watched = watching();
  const feedRun = newRunId();
  const t0 = Date.now();
  const feed = (e: WatchEvent) => publish(feedRun, t0, e);
  const observed = watched ? observeDeps(base, feed) : base;
  if (watched) {
    feed({
      type: "run_start",
      agentId: agent.id,
      agentName: agent.name,
      user: { id: `workflow:${workflowId}`, name: `Workflow ${workflowId}`, role: "workflow", email: null },
      message: step.task,
      conversationId: conversationIdOf(workflowRunId, stepId),
      workflow: { id: workflowId, runId: workflowRunId, stepId },
    });
  }

  const deps: StepDeps = {
    callModel: observed.callModel,
    trace: observed.trace,
    turns: base.turns,
    evalExpression: base.evalExpression,
    modelReady: modelConfigured,
    runToolAs(approvedWrites, identity) {
      // The actor always holds the assistant's READ tools; a data-changing tool only when the gates approved it.
      const reads = agent.tools.filter((t) => !changesData(t)).map((t) => t.name);
      const actor = makeActor({ ...identity, agentId: agent.id, tools: agent.tools, granted: [...reads, ...approvedWrites] });
      const io = workflowToolIO(actor, toolIO, dataLayer);
      return guardTools(actor, agent.tools, createToolRunner(watched ? instrumentIO(io, feed) : io, limiter), logToConsole);
    },
    async afterRecord() {
      // A host that freezes the process right after the request finishes waits here for the turn to be sent.
      const { insightsShipper } = await import("./insights-outbox");
      const { holdForShipping } = await import("./insights-shipper");
      await holdForShipping(insightsShipper(), process.env);
    },
  };

  const outcome = await runAgentStep(agent, step, { workflowId, workflowRunId, stepId }, deps, (e) => {
    if (watched) feed(feedEvent(e));
  });
  return finish(outcome);
}

export function registerAgentStepAction(): void {
  registerActionHandler("agent_step", agentStepAction);
}
