/**
 * Workflow Execution Engine
 *
 * Loads workflow definitions from /workflows/*.json and executes them.
 * Walks the node graph following edges, evaluates conditions with FEEL-lite,
 * and dispatches actions to registered handlers.
 *
 * Designed to run server-side in a Next.js API route.
 */

import { evaluateExpression } from "../feel-lite";
import type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  WorkflowExecutionContext,
  WorkflowExecutionResult,
  ExecutionLogEntry,
  NodeConfig,
  ActionHandler,
  ParallelApproverGroup,
  StageV2,
  StageMode,
  DelegationRule,
} from "./types";
import {
  resolveInputMappings,
  applyOutputMappings,
  writeExecutionLog,
  type InputMapping,
  type OutputMapping,
} from "./node-io";
import { evaluateDecision } from "./decision";

/**
 * Action handler registry. The generated app registers handlers
 * for db_query, http_call, send_email, etc.
 */
const actionHandlers: Map<string, ActionHandler> = new Map();

export function registerActionHandler(
  actionType: string,
  handler: ActionHandler,
): void {
  actionHandlers.set(actionType, handler);
}

export function getActionHandler(
  actionType: string,
): ActionHandler | undefined {
  return actionHandlers.get(actionType);
}

/**
 * Execute a workflow definition.
 *
 * Walks the node graph starting from the trigger node, evaluating
 * conditions and dispatching actions until reaching an end node
 * or running out of edges.
 */
export async function executeWorkflow(
  workflow: WorkflowDefinition,
  input: Record<string, unknown>,
  user?: WorkflowExecutionContext["user"],
): Promise<WorkflowExecutionResult> {
  const startedAt = new Date().toISOString();

  const ctx: WorkflowExecutionContext = {
    input,
    variables: { ...input },
    log: [],
    user,
  };
  // Wire workflowId onto ctx so execution-log rows and reportFromError
  // locators aren't blank. writeExecutionLog reads `(ctx as any).workflowId`
  // — the pre-fix comment claimed line 74 populated it but it never did,
  // and every log row shipped with workflowId="". See workflow-audit
  // reliability honorable mentions.
  (ctx as any).workflowId = workflow.id;
  // Fork/join barrier state. Every parallel branch spread-copies ctx, so the
  // Map MUST live on the shared root ctx — creating it lazily inside the join
  // handler gave each branch its own Map, arrivals never reached the expected
  // count, and the join silently deadlocked (run reported "completed" with
  // every downstream node skipped). Initializing here forces the reference to
  // be shared across all branch copies.
  (ctx as any).__joinCounters = new Map();
  // Same reason for the resume idempotency markers — a marker written inside
  // one parallel branch must be visible to its siblings and to a later
  // resume. Kept on the root ctx so both parallel branches AND
  // process-restart replay see the same set.
  (ctx as any).__completed = (ctx as any).__completed ?? new Set();
  // The names this workflow DECLARES as process variables.
  //
  // `_resolveValueMap` in index.ts has to tell a reference-to-a-variable
  // apart from a literal value, and the untyped `values` map conflates
  // them: `{status: "Rejected"}` and `{landlordId: "landlordId"}` are
  // both bare identifiers absent from ctx.variables. It used to guess
  // from the STRING'S SHAPE — dropping anything matching /^\w+$/ — which
  // silently deleted every one-word status write while a two-word value
  // went through. The declaration is the only real authority for which
  // names are variables, so publish it here rather than guessing there.
  (ctx as any).__declaredVars = new Set(
    (workflow.processVariables ?? [])
      .map((v) => (v && typeof v === "object" ? (v as any).name : undefined))
      .filter((n): n is string => typeof n === "string" && n.length > 0),
  );

  // Find the trigger node (entry point)
  const triggerNode = workflow.definition.nodes.find(
    (n) => n.type === "trigger" || n.data.nodeType === "trigger",
  );

  if (!triggerNode) {
    return {
      workflowId: workflow.id,
      workflowName: workflow.name,
      startedAt,
      completedAt: new Date().toISOString(),
      status: "failed",
      log: ctx.log,
      output: ctx.variables,
      error: "No trigger node found",
    };
  }

  try {
    await executeNode(triggerNode, workflow, ctx);

    // Check if workflow paused at a human task.
    //
    // Scans EVERY log entry, not just the tail. Reading only the last
    // entry worked for a sequential graph but silently lost an approval
    // inside a fork: sibling branches keep logging after the approval
    // pauses, so the tail was whichever branch happened to finish last.
    // The run then reported "completed" with no pendingTask,
    // persistPendingTask never fired, and the approval was gone — the
    // user saw a success and the task never reached anyone's inbox.
    //
    // First match wins so the reported pausedAt is the earliest node
    // actually waiting, which is deterministic regardless of the order
    // branches happen to settle in.
    const pausedLog = ctx.log.find(
      (l) => l?.status === "running" && (l as any)?.output?.waitingForHumanAction,
    );
    const lastLog = pausedLog;
    const isPaused = Boolean(pausedLog);

    return {
      workflowId: workflow.id,
      workflowName: workflow.name,
      startedAt,
      completedAt: isPaused ? undefined : new Date().toISOString(),
      status: isPaused ? "paused" : "completed",
      log: ctx.log,
      output: ctx.variables,
      pausedAt: isPaused ? lastLog.nodeId : undefined,
      pendingTask: isPaused ? {
        nodeId: lastLog.nodeId,
        nodeLabel: lastLog.nodeLabel,
        taskType: lastLog.output?.taskType,
        assignee: lastLog.output?.assignee,
        assigneeRole: lastLog.output?.assigneeRole,
        assignmentStrategy: lastLog.output?.assignmentStrategy,
        assigneePool: lastLog.output?.assigneePool,
        formBinding: lastLog.output?.formBinding,
        dueIn: lastLog.output?.dueIn,
        formId: lastLog.output?.formId,
        // Escalation policy recorded by an upstream `escalation` node
        // (case "escalation" writes ctx.variables.__escalationPolicy).
        // persistPendingTask reads this to set workflow_tasks.escalate_to
        // + due_at so processEscalations can reassign on SLA breach.
        escalationPolicy: ctx.variables.__escalationPolicy,
      } : undefined,
    } as WorkflowExecutionResult;
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    // Definition-level onFailure: best-effort cleanup so long multi-step
    // workflows (scan → AI → N scrapes) don't strand their tracking row in
    // "processing"/"pending" when a mid-run node throws. Runs as a synthetic
    // action node with the failure message published as {{__error}}. Its own
    // failure is swallowed — cleanup must never mask the original error.
    const onFailure = (workflow as any).onFailure;
    if (onFailure && typeof onFailure === "object" && (onFailure as any).actionType) {
      try {
        ctx.variables.__error = error;
        const syntheticNode = {
          id: "__on_failure",
          type: "action",
          position: { x: 0, y: 0 },
          data: {
            label: "onFailure cleanup",
            nodeType: "action",
            config: onFailure as Record<string, unknown>,
          },
        } as unknown as WorkflowNode;
        await handleAction(syntheticNode, ctx);
      } catch (cleanupErr) {
        console.warn("[workflow] onFailure cleanup failed:", cleanupErr);
      }
    }
    return {
      workflowId: workflow.id,
      workflowName: workflow.name,
      startedAt,
      completedAt: new Date().toISOString(),
      status: "failed",
      log: ctx.log,
      output: ctx.variables,
      error,
    };
  }
}

/**
 * Resolve input parameters for a node from process variables.
 */
function resolveInputParams(
  node: WorkflowNode,
  ctx: WorkflowExecutionContext,
): Record<string, unknown> {
  const resolved: Record<string, unknown> = {};
  const params = node.data.inputParams || [];

  for (const param of params) {
    const source = param.source || param.name;
    if (source in ctx.variables) {
      resolved[param.name] = ctx.variables[source];
    } else if (param.defaultValue !== undefined) {
      resolved[param.name] = param.defaultValue;
    } else if (source in ctx.input) {
      resolved[param.name] = ctx.input[source];
    }
  }

  return resolved;
}

/**
 * Write output parameters from node execution back to process variables.
 */
function writeOutputParams(
  node: WorkflowNode,
  output: unknown,
  ctx: WorkflowExecutionContext,
): Record<string, unknown> {
  const produced: Record<string, unknown> = {};
  const params = node.data.outputParams || [];
  const outputObj = (typeof output === "object" && output !== null) ? output as Record<string, unknown> : {};

  for (const param of params) {
    const target = param.target || param.name;
    const value = param.name in outputObj ? outputObj[param.name] : outputObj;
    ctx.variables[target] = value;
    produced[target] = value;
  }

  // If no explicit output params, expose the raw handler output under BOTH
  // the bare node id and the legacy `__<node>_output` key. Every emitter
  // (archetype and LLM-authored) uses plain `{{stepId.field.path}}` — e.g.
  // `{{create_session.inserted.id}}` — so the engine has to make that walk
  // work at all. Without the bare-id form, the very next db_update in a
  // pipeline sees an empty WHERE and refuses to run ("trigger form is
  // missing an input for this workflow node"), and the whole graph stops.
  // The `__<node>_output` alias is kept for older workflow JSON that still
  // references it explicitly.
  if (params.length === 0 && output !== undefined) {
    ctx.variables[node.id] = output;
    ctx.variables[`__${node.id}_output`] = output;
    // Emitters (and every gen-time guard: workflow_mutation_guard,
    // file_first_forms, workflow_validator) also declare a step's output as
    // `config.outputVar` (aliases below) — e.g. an http_call OCR step with
    // outputVar "ocrResult" consumed downstream as `{{ocrResult.text}}`.
    // Publish under that name too — overwriting, so a re-executed step
    // (loop back-edge) refreshes it and a same-named trigger input is
    // shadowed by the step's real output. `custom` and `set_variable` are
    // exempt: their handlers already assign the RAW result to the target
    // name themselves, and this wrapper object must not clobber it.
    const cfg = (node.data.config ?? {}) as Record<string, unknown>;
    const action = String(cfg.actionType ?? "");
    if (action !== "custom" && action !== "set_variable") {
      for (const key of ["outputVar", "resultVar", "resultVariable", "outputVariable"]) {
        const name = cfg[key];
        if (typeof name === "string" && name) {
          ctx.variables[name] = output;
          produced[name] = output;
        }
      }
    }
  }

  return produced;
}

/**
 * Execute a single node and follow outgoing edges.
 *
 * Flow:
 *   1. Resolve inputParams from process variables
 *   2. Execute the node (action, condition, approval, etc.)
 *   3. Write outputParams back to process variables
 *   4. Follow outgoing edges to the next node(s)
 */
// Hard ceiling on how many nodes a single run may execute. A workflow
// author who accidentally wires a loop-back edge used to blow the JS
// stack; this budget stops the walk at a reasonable value and fails
// the run so the missing exit is visible. 5000 is enormous for real
// workflows (a paused → resumed run recurses the whole graph again,
// so the number is roughly `nodes × resumes × parallel branches`).
const _MAX_STEPS = 5000;

// Hard ceiling on RECURSION DEPTH, which is a different quantity from
// total steps and is the one that actually overflows.
//
// The step budget alone was unreachable dead code: a linear cycle
// recurses once per step, and the JS stack dies at ~1645 nested
// `executeNode` frames — well before 5000. The author got a raw
// `RangeError: Maximum call stack size exceeded` plus escaping unhandled
// rejections instead of the diagnostic the guard was written to produce.
//
// Depth is counted in OUR frames rather than inferred from the engine's
// stack, so this fires deterministically regardless of platform, Node
// version or frame size. 200 is far beyond any real workflow: depth is
// the longest PATH through the graph, not the node count, and a resumed
// run re-walks the same path rather than a deeper one.
const _MAX_DEPTH = 200;

async function executeNode(
  node: WorkflowNode,
  workflow: WorkflowDefinition,
  ctx: WorkflowExecutionContext,
  depth: number = 0,
): Promise<void> {
  ctx.currentNodeId = node.id;

  // ─── Cycle guard, part 1: total work ──────────────────────────────
  // The budget lives in a CELL held by reference, not as a number on
  // ctx. `executeParallelBranches` shallow-spreads the context, and a
  // spread COPIES a number — so every branch used to inherit the
  // parent's count and then increment only its own copy. A cycle
  // through a fork therefore never accumulated toward the ceiling: it
  // recursed once per outgoing edge concurrently, live promises
  // multiplied ~2^depth, and V8 aborted the whole process with a heap
  // OOM (exit 134) rather than the run failing. Same reasoning as
  // `__joinCounters` / `__completed` in executeWorkflow — shared
  // mutable state must be a reference type.
  const budget: { steps: number } =
    (ctx as any).__stepBudget ??
    ((ctx as any).__stepBudget = { steps: 0 });
  budget.steps += 1;
  if (budget.steps > _MAX_STEPS) {
    throw new Error(
      `[cycle-guard] workflow exceeded ${_MAX_STEPS} node executions — likely a loop-back edge; last node: ${node.data?.label || node.id}`,
    );
  }

  // ─── Cycle guard, part 2: recursion depth ─────────────────────────
  // Passed as a PARAMETER, not stored on ctx: depth must unwind when a
  // call returns. Stored on ctx it would accumulate across siblings and
  // falsely trip on a wide-but-shallow graph.
  if (depth > _MAX_DEPTH) {
    throw new Error(
      `[cycle-guard] workflow exceeded ${_MAX_DEPTH} nested node executions — likely a loop-back edge; last node: ${node.data?.label || node.id}`,
    );
  }

  // ─── T5 resume-idempotency ─────────────────────────────────────────
  // If this node was already completed on a prior run (marker seeded
  // into ctx.variables via /execute route reading
  // workflow_tasks.process_variables), short-circuit: emit a
  // synthetic log entry, replay cached edges, do NOT re-run the
  // action. Prevents duplicate db_insert / http_call on resume.
  // user_task / approval nodes have their own decision-based
  // short-circuit further down and are excluded here.
  const _completedKey = `__step_${node.id}_completed`;
  if (
    node.type !== "user_task" &&
    node.type !== "approval" &&
    ctx.variables[_completedKey]
  ) {
    const cachedOutput = ctx.variables[`__step_${node.id}_output`];
    ctx.log.push({
      nodeId: node.id,
      nodeLabel: node.data.label,
      nodeType: node.type,
      startedAt: new Date().toISOString(),
      completedAt: new Date().toISOString(),
      resolvedInputs: {},
      status: "completed",
      output: cachedOutput,
      skippedResume: true,
    } as ExecutionLogEntry);

    // For conditions: replay the branch decision so downstream nodes
    // see the same edges as the first run.
    const cachedBranch = ctx.variables[`__step_${node.id}_branch`];
    let replayedEdges: WorkflowEdge[];
    if (Array.isArray(cachedBranch) && cachedBranch.length > 0) {
      const branchIds = new Set(cachedBranch.map(String));
      replayedEdges = workflow.definition.edges.filter(
        (e) => e.source === node.id && branchIds.has(e.id),
      );
    } else {
      replayedEdges = workflow.definition.edges.filter(
        (e) => e.source === node.id,
      );
    }
    for (const edge of replayedEdges) {
      const nextNode = workflow.definition.nodes.find(
        (n) => n.id === edge.target,
      );
      if (nextNode) await executeNode(nextNode, workflow, ctx, depth + 1);
    }
    return;
  }

  // Resolve input parameters
  const resolvedInputs = resolveInputParams(node, ctx);

  const logEntry: ExecutionLogEntry = {
    nodeId: node.id,
    nodeLabel: node.data.label,
    nodeType: node.type,
    startedAt: new Date().toISOString(),
    resolvedInputs,
    status: "running",
  };
  ctx.log.push(logEntry);

  let nextEdges: WorkflowEdge[] = [];
  const config = node.data.config || {};

  try {
    switch (node.type) {
      case "trigger": {
        // Apply trigger input mapping: payload fields → process variables
        const inputMapping = workflow.definition.trigger.inputMapping;
        if (inputMapping) {
          for (const [payloadField, processVar] of Object.entries(inputMapping)) {
            if (payloadField in ctx.input) {
              ctx.variables[processVar] = ctx.input[payloadField];
            }
          }
        } else {
          // Default: copy all input fields to process variables
          Object.assign(ctx.variables, ctx.input);
        }
        nextEdges = workflow.definition.edges.filter(
          (e) => e.source === node.id,
        );
        break;
      }

      case "condition":
      case "exclusive_gateway": {
        const cond = await handleCondition(node, workflow, ctx);
        // Surface enough on the log entry to answer "why did it take this
        // branch?" in the simulator/history — pre-fix, logs said only ✓/✗
        // node_label and the condition was a black box.
        logEntry.output = {
          expression: cond.expression,
          evaluated: cond.evaluated,
          branch: cond.evaluated ? "then" : "else",
          takenEdges: cond.edges.map((e) => e.target),
        };
        if (cond.evalError) {
          // A typo'd expression used to silently route every run down the
          // else branch AND discard the error. Fail the run so the author
          // sees the message; the "unknown table" pattern (line ~325 in
          // the action case) is the model.
          logEntry.error = `Condition eval failed: ${cond.evalError}`;
          throw new Error(
            `[condition ${node.data?.label || node.id}] expression eval failed: ${cond.evalError} — expression was: ${cond.expression || "(empty)"}`,
          );
        }
        if (cond.edges.length === 0) {
          // Truthy result with no then/default/unlabeled edge, or falsy
          // with no else edge — either way the walk silently ends and the
          // run reports "completed" mid-graph. Fail loudly so the missing
          // edge is visible.
          throw new Error(
            `[condition ${node.data?.label || node.id}] no ${cond.evaluated ? "then/default" : "else"} edge defined — workflow ends silently mid-graph`,
          );
        }
        nextEdges = cond.edges;
        break;
      }

      case "action":
      case "ai_generate":
      case "ai_classify":
      case "ai_extract":
      case "ai_decide": {
        // ─── R3: wait_for_event — pause until a matching bus event ────
        // Reuses the ONE pause/persist/resume mechanism the engine has
        // (the human-task path): the log entry stays "running" with
        // `waitingForHumanAction` set, executeWorkflow reports the run
        // as paused, persistPendingTask writes a workflow_tasks row
        // (task_type "wait_for_event"), and processPendingEvents
        // (events/bus.ts) resumes it by re-triggering with the T5
        // completion markers — the entry-check short-circuit at the top
        // of executeNode then replays this node with the event payload
        // as its cached output. On resume this branch is never reached,
        // so it only ever needs to pause. Do NOT invent a second
        // persistence mechanism here.
        if (String((config as any).actionType ?? "") === "wait_for_event") {
          const awaitedEvent = String((config as any).event ?? "").trim();
          const timeoutMs = Number((config as any).timeoutMs) || 0;
          logEntry.status = "running";
          logEntry.output = {
            taskCreated: true,
            taskType: "wait_for_event",
            waitingForHumanAction: true, // THE pause flag — see executeWorkflow's scan
            waitingForEvent: awaitedEvent,
            // persistPendingTask reads dueIn (minutes) into due_at, so an
            // authored timeout is at least visible/escalatable.
            dueIn: timeoutMs > 0 ? Math.ceil(timeoutMs / 60_000) : undefined,
            resolvedInputs,
          };
          // Rides into workflow_tasks.process_variables via
          // persistPendingTask; processPendingEvents matches on it.
          // Literal kept in sync with WAITING_EVENT_VAR in
          // ../events/triggers.ts.
          ctx.variables.__waiting_event = awaitedEvent;
          if (!awaitedEvent) {
            throw new Error(
              `[wait_for_event ${node.data?.label || node.id}] config.event is empty — the node would wait forever`,
            );
          }
          nextEdges = [];
          break;
        }
        // Make resolved inputs available in the context for action handlers
        ctx.variables.__currentInputs = resolvedInputs;
        const actionOutput = await handleAction(node, ctx, logEntry);
        logEntry.output = actionOutput;
        // A handler that returns { error } (e.g. db_insert "unknown table") failed
        // without throwing. Surface it so the workflow reports `failed` instead of a
        // misleading `completed` that makes the UI look like nothing happened.
        if (
          actionOutput && typeof actionOutput === "object" &&
          (actionOutput as { error?: unknown }).error
        ) {
          throw new Error(
            `${node.data.label || node.type}: ${(actionOutput as { error?: unknown }).error}`,
          );
        }
        // Write outputs back to process variables
        const producedOutputs = writeOutputParams(node, actionOutput, ctx);
        logEntry.producedOutputs = producedOutputs;
        const outgoing = workflow.definition.edges.filter(
          (e) => e.source === node.id,
        );
        if (node.type === "ai_decide") {
          // A decision is a branch, not a fan-out: take the then-edges on a
          // positive decision and the else-edges otherwise — the same rule a
          // condition node applies, and the one the editor's handles, the
          // projection's edges and the platform engine all assume.
          const decision = !!(actionOutput as { decision?: unknown } | null)?.decision;
          nextEdges = branchEdges(outgoing, decision);
          // Same shape the condition case logs, so the simulator/history can
          // answer "why did it take this branch?" for a decision too.
          logEntry.output = {
            ...(actionOutput && typeof actionOutput === "object" ? actionOutput : { output: actionOutput }),
            branch: decision ? "then" : "else",
            takenEdges: nextEdges.map((e) => e.target),
          };
          if (nextEdges.length === 0 && outgoing.length > 0) {
            console.warn(
              `[ai_decide ${node.data?.label || node.id}] no ${decision ? "then/default" : "else"} edge defined — workflow ends silently mid-graph`,
            );
          }
        } else {
          nextEdges = outgoing;
        }
        break;
      }

      case "parallel_gateway":
      case "fork":
        nextEdges = workflow.definition.edges.filter(
          (e) => e.source === node.id,
        );
        // For fork: execute all branches in parallel
        if (node.type === "fork" || node.type === "parallel_gateway") {
          await executeParallelBranches(nextEdges, workflow, ctx, depth);
          nextEdges = []; // Don't continue sequentially
        }
        break;

      case "wait": {
        // Cap wait to 5 seconds in execution — real delays should use scheduling
        const waitMs = Math.min(Number(config.duration || 0), 5000);
        if (waitMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, waitMs));
        }
        logEntry.output = { waitedMs: waitMs, requestedMs: config.duration };
      }
        nextEdges = workflow.definition.edges.filter(
          (e) => e.source === node.id,
        );
        break;

      case "user_task":
      case "approval":
      case "assignment":
      case "task_pool":
        // Human task: pause workflow and return pending status.
        // The caller should persist the workflow state and create a task
        // for the assignee. When the task is completed (via the execute
        // endpoint with the completed step), resume from this node.
        logEntry.status = "running";
        // The editor stores assignment as a nested { strategy, value } object
        // (value = the role to rotate/balance among, or a direct user/role);
        // also accept flat fields. The persist layer resolves the actual assignee
        // from the pool when strategy is round_robin / load_balanced.
        const _asn = (config as any).assignment || {};
        logEntry.output = {
          taskCreated: true,
          taskType: node.type,
          assignee: config.assignee || _asn.value || config.assigneeRole || "admin",
          assigneeRole: config.assigneeRole || _asn.value,
          assignmentStrategy: (config as any).assignmentStrategy ?? _asn.strategy,
          assigneePool: (config as any).assigneePool ?? _asn.pool,
          formBinding: config.formBinding,
          dueIn: config.dueIn,
          resolvedInputs,
          waitingForHumanAction: true,
        };

        // Apply a DOWNSTREAM escalation node's SLA at pause time.
        //
        // An `escalation` node is modelled here as a sequential pass-through,
        // but its BPMN semantics are a BOUNDARY EVENT on the human task that
        // precedes it. A human task pauses and returns no edges, so a node
        // wired after it is never walked to — the escalation therefore never
        // executed, `__escalationPolicy` was never set, and persistPendingTask
        // wrote the task row with escalate_to = NULL and no due_at. The SLA
        // the author configured could never fire, and nothing reported it.
        //
        // The policy has to be read at the moment the task is created, which
        // is here. Only immediate successors are considered — this is a
        // boundary event on THIS task, not a search of the whole graph.
        if (!ctx.variables.__escalationPolicy) {
          const escNode = workflow.definition.edges
            .filter((e) => e.source === node.id)
            .map((e) => workflow.definition.nodes.find((n2) => n2.id === e.target))
            .find((n2) => n2?.type === "escalation");
          if (escNode) {
            const ecfg = (escNode.data?.config || {}) as Record<string, unknown>;
            const policy = {
              slaHours: Number(ecfg.slaHours) || null,
              escalateTo: (ecfg.escalateTo as string) || null,
              nodeId: escNode.id,
            };
            ctx.variables.__escalationPolicy = policy;
            (logEntry.output as Record<string, unknown>).escalationPolicy = policy;
            // Record that the boundary node was applied, so it is visible in
            // the execution log rather than appearing never to have run.
            ctx.log.push({
              nodeId: escNode.id,
              nodeLabel: escNode.data?.label ?? escNode.id,
              nodeType: escNode.type,
              startedAt: new Date().toISOString(),
              completedAt: new Date().toISOString(),
              resolvedInputs: {},
              status: "completed",
              output: { escalationScheduled: true, ...policy,
                        appliedAsBoundaryEventOf: node.id },
            } as ExecutionLogEntry);
          }
        }

        // Check if this step was already completed (resume scenario)
        const stepCompleted = ctx.variables[`__step_${node.id}_completed`];
        if (stepCompleted) {
          // Step was completed externally — continue to next node
          logEntry.status = "completed";
          logEntry.completedAt = new Date().toISOString();
          const decision = ctx.variables[`__step_${node.id}_decision`];
          const comment = ctx.variables[`__step_${node.id}_comment`];
          logEntry.output = {
            ...logEntry.output,
            waitingForHumanAction: false,
            completedBy: ctx.variables[`__step_${node.id}_completedBy`],
            decision,
          };
          // Write the decision into the approval node's declared outputParams so
          // downstream nodes (e.g. a db_update setting the entity's status) see
          // approved/rejected instead of the pending default. A status/decision-
          // like target gets the decision; a comment/note-like target gets the
          // comment. Fallback: the first target receives the decision.
          const outParams = ((node as any).data?.outputParams ||
            (config as any)?.outputParams ||
            []) as Array<{ target?: string; name?: string }>;
          let decisionTargetSet = false;
          for (const op of outParams) {
            const target = op?.target || op?.name;
            if (!target) continue;
            if (/status|decision|state|outcome|approv/i.test(target)) {
              ctx.variables[target] = decision;
              decisionTargetSet = true;
            } else if (comment !== undefined && /comment|note|reason/i.test(target)) {
              ctx.variables[target] = comment;
            }
          }
          if (!decisionTargetSet && outParams.length > 0) {
            const t = outParams[0]?.target || outParams[0]?.name;
            if (t) ctx.variables[t] = decision;
          }
          nextEdges = workflow.definition.edges.filter(
            (e) => e.source === node.id,
          );
        } else {
          // Not yet completed — PAUSE the workflow here
          // Return empty edges so the engine stops walking
          nextEdges = [];
        }
        break;

      case "decision": {
        // Rule-table evaluation: walk rows top-to-bottom, first matching
        // row's outputs are written back to ctx.variables. Syntax is
        // Tentoro's own (see decision.ts) — wildcards, equality,
        // numeric compare, ranges.
        const decisionOut = evaluateDecision(node.data.config || {}, ctx);
        logEntry.output = decisionOut;
        nextEdges = workflow.definition.edges.filter(
          (e) => e.source === node.id,
        );
        break;
      }

      case "escalation": {
        // Escalation node: BPMN semantics are a boundary event that
        // fires when the previous human task exceeds slaHours. We
        // don't have boundary-event graph edges yet, so treat the
        // node as a pass-through that records its policy into the
        // pending-task's process variables for `processEscalations`
        // to pick up. Never silently skip.
        const slaHours = Number((config as any).slaHours) || null;
        const escalateTo = (config as any).escalateTo || null;
        ctx.variables.__escalationPolicy = { slaHours, escalateTo, nodeId: node.id };
        logEntry.output = {
          escalationScheduled: true,
          slaHours,
          escalateTo,
        };
        nextEdges = workflow.definition.edges.filter(
          (e) => e.source === node.id,
        );
        break;
      }

      case "join": {
        // Arrival barrier — hold the downstream walk until every
        // inbound branch has arrived.
        //
        // Counter lives on a shared Map hung off ctx itself (not on
        // ctx.variables), because executeParallelBranches gives each
        // branch a SHALLOW-COPIED variables map. If we stored the
        // counter under ctx.variables[...], two branches racing on the
        // join would both read 0 and write 1 into their own copies —
        // parent-side merge (Object.assign) is last-write-wins so the
        // counter would peg at 1 and the join would deadlock. Storing
        // it on ctx directly (which IS shared by reference across
        // branches — see the `{...ctx, variables: {...}}` spread in
        // executeParallelBranches) makes the increments compose.
        const counters: Map<string, number> =
          (ctx as any).__joinCounters ??
          ((ctx as any).__joinCounters = new Map<string, number>());
        const inbound = workflow.definition.edges.filter((e) => e.target === node.id);
        const expected = inbound.length;
        const arrived = (counters.get(node.id) ?? 0) + 1;
        counters.set(node.id, arrived);
        if (arrived < expected) {
          logEntry.output = { joined: false, arrived, expected };
          nextEdges = [];
        } else {
          logEntry.output = { joined: true, arrived, expected };
          nextEdges = workflow.definition.edges.filter((e) => e.source === node.id);
        }
        break;
      }

      case "end":
      case "end_event":
        // Terminal node — workflow complete
        nextEdges = [];
        break;

      default:
        // Unknown node type — log and skip
        logEntry.output = { skipped: true, reason: `Unknown node type: ${node.type}` };
        nextEdges = workflow.definition.edges.filter(
          (e) => e.source === node.id,
        );
    }

    // Don't overwrite paused status for approval/user_task nodes
    if (logEntry.status !== "running" || !logEntry.output?.waitingForHumanAction) {
      logEntry.status = "completed";
      logEntry.completedAt = new Date().toISOString();

      // ─── T5 resume-idempotency: mark node completed ─────────────
      // Persist a completion marker so a later resume (which
      // re-executes from the trigger) can short-circuit at the
      // executeNode entry check above. Skip user_task / approval —
      // those have their own decision-based short-circuit.
      //
      // Also skip a join whose barrier did NOT fire. Such a join has
      // been reached but is still waiting on other branches, so it is
      // the opposite of completed. Marking it completed wrote
      // `__step_<id>_completed` into ctx.variables, which is persisted
      // to workflow_tasks.process_variables and reloaded on resume —
      // where the entry check would skip the join entirely and replay
      // its (empty) edges. The barrier would be bypassed on every
      // resumed run, letting downstream nodes fire before their
      // remaining branches had arrived.
      const barrierHeld =
        node.type === "join" && (logEntry.output as any)?.joined === false;

      if (node.type !== "user_task" && node.type !== "approval" && !barrierHeld) {
        ctx.variables[`__step_${node.id}_completed`] = true;
        ctx.variables[`__step_${node.id}_output`] = logEntry.output;
        // For conditions: cache the branch edge ids so the resumed
        // run takes the same path (avoids a re-evaluated expression
        // returning a different decision).
        if (
          (node.type === "condition" || node.type === "exclusive_gateway") &&
          nextEdges.length > 0
        ) {
          ctx.variables[`__step_${node.id}_branch`] = nextEdges.map((e) => e.id);
        }
      }
    }
  } catch (err) {
    logEntry.status = "failed";
    logEntry.error = err instanceof Error ? err.message : String(err);
    logEntry.completedAt = new Date().toISOString();
    throw err;
  }

  // Continue to next nodes
  for (const edge of nextEdges) {
    const nextNode = workflow.definition.nodes.find((n) => n.id === edge.target);
    if (nextNode) {
      await executeNode(nextNode, workflow, ctx, depth + 1);
    }
  }
}

/**
 * Handle condition nodes — evaluate FEEL-lite expression and select edge.
 *
 * Returns the selected edges plus the metadata needed to render a
 * meaningful log entry (the expression, its evaluated value, and any
 * eval error). Silently mapping an eval error to `false` used to route
 * every run down the `else` branch AND discard the error — so a typo
 * in the expression looked identical to a legitimate false result, and
 * a mis-typed variable path silently rejected every candidate. The
 * caller (executeNode) uses `evalError` to fail the run loudly.
 */
export interface ConditionResult {
  edges: WorkflowEdge[];
  expression: string;
  evaluated: unknown;
  evalError?: string;
}

/**
 * Compile the editor's visual condition tree into a FEEL-lite expression.
 *
 * A14-1: `ConditionModeToggle` persists only `config.conditionTree`; nothing
 * ever compiled it into `config.expression`, and this engine reads ONLY
 * `expression`. An empty expression evaluates to TRUE, so every visually
 * authored condition took its `then` branch, the `else` branch was dead, and
 * the run reported `completed` — no error, no crash, and a matching edge, so
 * none of the loud-failure guards could fire.
 *
 * Compiling HERE rather than in the editor is deliberate: workflows already
 * saved carry a tree and no expression, so an editor-only fix would leave every
 * existing one broken until someone re-opened and re-saved it.
 *
 * The editor has shipped two operator vocabularies (`gt` and `greater_than`),
 * so both are accepted — supporting only one would silently resurrect this
 * defect for whichever half of the corpus used the other.
 */
function compileConditionTree(tree: unknown): string {
  const lit = (v: unknown): string => {
    if (v === null || v === undefined) return "null";
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    if (Array.isArray(v)) return `[${v.map(lit).join(", ")}]`;
    return JSON.stringify(String(v));
  };

  const OPS: Record<string, string> = {
    equals: "=", eq: "=", not_equals: "!=", neq: "!=", ne: "!=",
    gt: ">", greater_than: ">", gte: ">=", greater_than_or_equal: ">=",
    lt: "<", less_than: "<", lte: "<=", less_than_or_equal: "<=",
  };

  const compile = (node: any): string => {
    if (!node || typeof node !== "object") return "true";

    if (node.type === "group" || Array.isArray(node.children)) {
      const joiner = String(node.operator ?? "AND").toUpperCase() === "OR" ? " or " : " and ";
      const parts = (node.children ?? []).map(compile).filter((p: string) => p && p !== "true");
      if (!parts.length) return "true";
      return parts.length === 1 ? parts[0] : `(${parts.join(joiner)})`;
    }

    const field = String(node.field ?? "").trim();
    if (!field) return "true";
    const op = String(node.operator ?? "equals");

    if (op === "is_null") return `${field} = null`;
    if (op === "is_not_null") return `${field} != null`;
    if (op === "contains") return `contains(${field}, ${lit(node.value)})`;
    if (op === "starts_with") return `starts_with(${field}, ${lit(node.value)})`;
    if (op === "ends_with") return `ends_with(${field}, ${lit(node.value)})`;
    if (op === "in" || op === "not_in") {
      const list = Array.isArray(node.value) ? node.value : [node.value];
      const any = list.map((v: unknown) => `${field} = ${lit(v)}`).join(" or ");
      return op === "in" ? `(${any})` : `not(${any})`;
    }

    const sym = OPS[op];
    // An unknown operator must NOT quietly become `true` — that is exactly the
    // silent-success shape this defect had. Emit something the evaluator
    // rejects so the failure is loud.
    if (!sym) return `__unsupported_condition_operator_${op}__`;
    return `${field} ${sym} ${lit(node.value)}`;
  };

  return compile(tree);
}

async function handleCondition(
  node: WorkflowNode,
  workflow: WorkflowDefinition,
  ctx: WorkflowExecutionContext,
): Promise<ConditionResult> {
  const config = node.data.config || {};
  // A14-1: fall back to the visual builder's tree when no expression was
  // compiled. An authored expression still wins when both are present.
  const expression =
    String(config.expression || "") ||
    ((config as any).conditionTree ? compileConditionTree((config as any).conditionTree) : "");

  let result: unknown;
  let evalError: string | undefined;
  try {
    result = expression
      ? evaluateExpression(expression, ctx.variables as any)
      : true;
  } catch (err) {
    result = false;
    evalError = err instanceof Error ? err.message : String(err);
  }

  const allEdges = workflow.definition.edges.filter((e) => e.source === node.id);
  const edges = branchEdges(allEdges, !!result);

  return { edges, expression, evaluated: result, evalError };
}

/**
 * The outgoing edges a yes/no outcome takes: the `then` edges (or unlabelled /
 * `default` ones) when taken, the `else` edges when not. One rule for every
 * node that branches on a boolean — `condition`, `exclusive_gateway` and
 * `ai_decide` — so they cannot drift. `ai_decide` used to skip this and follow
 * every outgoing edge, so a two-branch decision ran both branches.
 */
function branchEdges(allEdges: WorkflowEdge[], taken: boolean): WorkflowEdge[] {
  return taken
    ? allEdges.filter(
        (e) =>
          e.data?.edgeType === "then" ||
          e.data?.edgeType === "default" ||
          !e.data?.edgeType,
      )
    : allEdges.filter((e) => e.data?.edgeType === "else");
}

/**
 * Dispatch action nodes to registered handlers.
 */
async function handleAction(
  node: WorkflowNode,
  ctx: WorkflowExecutionContext,
  ownLogEntry?: ExecutionLogEntry,
): Promise<unknown> {
  const rawConfig = node.data.config || {};

  // Merge the new contract-shape inputMappings on top of the flat legacy
  // config so handlers see the union. Contract-mapped values WIN when
  // both are present — the panel author's intent overrides any leftover
  // legacy field that a migration didn't rewrite.
  const resolved = resolveInputMappings(
    (rawConfig as any).inputMappings as InputMapping[] | undefined,
    ctx.variables,
  );
  const config: any = { ...rawConfig, ...resolved };

  /**
   * A14-3: inputs whose mapping source is "expression" have ALREADY been
   * evaluated by resolveInputMappings — the resolved value is final.
   *
   * That matters for the inline actions below, which take a config key named
   * `expression` and evaluate it themselves. With an expression-sourced
   * mapping the string was evaluated once by the mapper and the RESULT was
   * then evaluated a second time as if it were source text: `amount * 2` with
   * amount=21 became 42, and 42 was re-evaluated as an expression. Whether
   * that happens to survive depends entirely on the value's shape, which is
   * the worst kind of bug — it works in testing and fails on real data.
   */
  const preEvaluated = new Set(
    (Array.isArray((rawConfig as any).inputMappings) ? (rawConfig as any).inputMappings : [])
      .filter(
        (m: any) =>
          m &&
          typeof m === "object" &&
          m.name &&
          // "expression" was evaluated by the mapper; "variable" was read out of
          // ctx.variables. Either way the resolved value is FINAL.
          //
          // "literal" is deliberately excluded: there the authored string IS the
          // expression source text, so the inline handler evaluating it is the
          // correct behaviour (case 14.6 pins that).
          (m.source === "expression" || m.source === "variable"),
      )
      .map((m: any) => String(m.name)),
  );

  /**
   * A0-8: the tail of handleAction — log the output and apply outputMappings —
   * used to be reachable only by the registered-handler path. `set_variable`
   * and `transform` are handled INLINE above and returned early, so promoting
   * one of their outputs to a process variable did nothing at all, silently.
   *
   * Inline branches return through here so they get the same treatment.
   */
  const finishInline = (result: unknown): unknown => {
    const entry = ownLogEntry ?? ctx.log[ctx.log.length - 1];
    if (entry) entry.output = result;
    applyOutputMappings(
      (rawConfig as any).outputMappings as OutputMapping[] | undefined,
      result,
      ctx.variables,
    );
    return result;
  };

  let actionType = config.actionType || (node.type as string);

  // For AI nodes, the action type is the node type itself
  if (
    node.type === "ai_generate" ||
    node.type === "ai_classify" ||
    node.type === "ai_extract" ||
    node.type === "ai_decide"
  ) {
    actionType = node.type;
  }

  // Handle set_variable inline. The panel emits `config.expression` (a
  // FEEL-lite expression to evaluate against ctx.variables); the
  // canonical precomputed key is `variableValue`. `value` is accepted
  // as an alias for on-disk back-compat with workflows generated
  // before the translator's key was fixed (workflow-audit P1-10).
  if (actionType === "set_variable" && config.variableName) {
    let value: unknown;
    if ("variableValue" in config) {
      value = (config as any).variableValue;
    } else if ("value" in (config as any)) {
      value = (config as any).value;
    } else if (preEvaluated.has("expression")) {
      // A14-3: already evaluated by the input mapper — using it directly is
      // the whole fix. Re-evaluating would be the double-evaluation bug.
      value = config.expression;
    } else if (typeof config.expression === "string" && config.expression.trim()) {
      try {
        value = evaluateExpression(String(config.expression), ctx.variables);
      } catch {
        // Fall back to treating the expression as a literal string so the
        // author's intent isn't silently swallowed on a syntax error.
        value = config.expression;
      }
    } else {
      value = undefined;
    }
    ctx.variables[config.variableName as string] = value;
    // A0-4: the contract advertises an output named `value`, but only the
    // DYNAMIC key was returned — so `{{n.output.value}}`, which is the only
    // thing the editor can offer for a name it cannot know at author time,
    // resolved to undefined. Return both.
    //
    // A0-8: `return` here used to exit handleAction BEFORE the common tail,
    // which is where applyOutputMappings runs — so an outputMapping on a
    // set_variable node was silently ignored no matter what this returned.
    // finishInline() runs the same tail every other action goes through.
    return finishInline({ [config.variableName as string]: value, value });
  }

  // Handle transform inline. Panel emits `config.expression`; legacy
  // shape used `config.transformExpression`. Accept either.
  if (actionType === "transform") {
    // A14-3: same double-evaluation risk as set_variable.
    if (preEvaluated.has("expression")) {
      return finishInline({ value: (config as any).expression });
    }
    const expr =
      (config as any).transformExpression ??
      (config as any).expression;
    if (typeof expr === "string" && expr.trim()) {
      // A0-5: this returned the bare scalar, so there was no object for
      // `{{n.output.value}}` — the one output the contract declares — to read
      // from. Wrapping it makes the declared path resolvable.
      // A0-8: same early-return problem as set_variable — see above.
      try {
        return finishInline({ value: evaluateExpression(String(expr), ctx.variables) });
      } catch {
        return finishInline({ value: null });
      }
    }
    // Same shape on the no-expression path, so a downstream binding always
    // finds `value` whether or not the node was configured.
    return finishInline({ value: null });
  }

  const handler = actionHandlers.get(actionType);
  if (!handler) {
    // RETURN the skip record rather than writing it to the log and
    // returning null.
    //
    // Two things erased this trace. It wrote to
    // `ctx.log[ctx.log.length - 1]` — the tail, which after a fork is some
    // other branch's entry — and then returned `null`, which executeNode
    // promptly assigned over `logEntry.output`, wiping whatever had just
    // been recorded. So an unregistered action type did nothing AND left
    // nothing behind: the run reported `completed`, the node showed no
    // output, and there was no way to tell it had been skipped.
    // STRICT by default — a node that declares an actionType with no
    // registered handler is almost always a planner bug (e.g. "set_variable"
    // authored by the LLM that has no runtime). Silent-skipping produced apps
    // that reported `completed` while critical steps did nothing. Throw so it
    // surfaces immediately; set FORGE_RUNTIME_STRICT=false to opt into the
    // old warn-and-continue behavior.
    const strict = process.env.FORGE_RUNTIME_STRICT !== "false";
    const message =
      `[workflow] node ${node.id} declares actionType "${actionType}" but no ` +
      `handler is registered — the node did NOTHING and the walk continued.`;
    if (strict) {
      throw new Error(
        `Unregistered workflow actionType "${actionType}" on node "${node.id}". ` +
        `Register a handler in the workflow runtime or fix the planner to emit a ` +
        `supported actionType. Set FORGE_RUNTIME_STRICT=false to downgrade to a warning.`,
      );
    }
    const skip = { skipped: true, reason: `No handler for action type: ${actionType}` };
    if (ownLogEntry) ownLogEntry.output = skip;
    console.warn(message);
    return skip;
  }

  // Inject resolved inputs into config so handlers can use them.
  // Also attach __nodeId + __workflowId so any reportFromError() call
  // in the handler can pass a real locator to Forge (the self-heal
  // anchor loader depends on these to pre-load the failing workflow
  // JSON for Smith).
  const enrichedConfig = {
    ...config,
    __resolvedInputs: ctx.variables.__currentInputs,
    __nodeId: node.id,
    // The context stores the workflow id at `ctx.workflowId` (see line 74
    // of this file — `executeWorkflow` populates it). Read that path
    // first; fall back to `ctx.workflow?.id` for any custom ctx shape.
    __workflowId:
      (ctx as unknown as { workflowId?: string }).workflowId ||
      (ctx as unknown as { workflow?: { id?: string } }).workflow?.id,
  };
  const startedAt = Date.now();
  let result: unknown = null;
  let runError: Error | null = null;
  try {
    result = await handler(enrichedConfig, ctx);
  } catch (err) {
    runError = err instanceof Error ? err : new Error(String(err));
  }
  const durationMs = Date.now() - startedAt;

  // Use THIS node's own log entry, handed in by executeNode.
  //
  // This used to re-derive the entry as `ctx.log[ctx.log.length - 1]`
  // — after the `await` above. `executeParallelBranches` shares the log
  // array by reference across branches, so while a slow handler awaited,
  // a faster sibling pushed its own entries and the slow handler then
  // wrote its result onto whichever entry happened to be last. Control
  // flow was unaffected (executeNode keeps the correct local reference),
  // which is exactly what made it invisible: the History tab and
  // workflow_execution_log silently attributed one node's output to a
  // different node, including to terminal nodes that run no handler at
  // all. The tail fallback is kept only for any caller that does not
  // pass an entry.
  const logEntry = ownLogEntry ?? ctx.log[ctx.log.length - 1];
  if (logEntry) {
    logEntry.output = runError ? { error: runError.message } : result;
  }

  // Promote declared outputs to named process variables (opt-in).
  if (!runError) {
    applyOutputMappings(
      (rawConfig as any).outputMappings as OutputMapping[] | undefined,
      result,
      ctx.variables,
    );
  }

  // Persist one execution-log row per node run. Fire-and-forget — the
  // runtime never blocks the workflow on observability writes.
  const runId =
    (ctx as any).runId ||
    (ctx as any).workflowInstanceId ||
    logEntry?.startedAt ||
    "";
  const workflowId =
    (ctx as unknown as { workflowId?: string }).workflowId ||
    (ctx as unknown as { workflow?: { id?: string } }).workflow?.id ||
    "";
  void writeExecutionLog({
    runId: String(runId),
    workflowId: String(workflowId),
    nodeId: node.id,
    nodeLabel: node.data?.label ?? node.id,
    actionType: String(actionType),
    stepIndex: Math.max(0, ctx.log.length - 1),
    inputs: resolved,
    outputs: runError ? null : (result as any),
    status: runError ? "failed" : "completed",
    error: runError?.message,
    durationMs,
  });

  if (runError) throw runError;
  return result;
}

// ── Wave 5 Extensions: Parallel Approvers + Conditional Routing + Delegation ──

/**
 * Read a nested value from an object by dot-path.
 * e.g. readPath({ a: { b: 42 } }, "a.b") === 42
 */
function readPath(obj: any, path: string): any {
  return path.split(".").reduce((acc, key) => acc?.[key], obj);
}

/**
 * Placeholder: look up a user ID by role.
 * Generated apps should replace this with a real DB query.
 */
function lookupByRole(_role: string): string | null {
  // Implement: query users table for a user with the given role
  return null;
}

/**
 * Check whether a date falls within an optional range.
 */
function isWithinDateRange(date: Date, from?: string, to?: string): boolean {
  if (from && date < new Date(from)) return false;
  if (to && date > new Date(to)) return false;
  return true;
}

/**
 * Resolve an approver group to a list of effective user IDs,
 * applying any active delegation rules.
 */
export function resolveApprovers(
  group: ParallelApproverGroup,
  context: { record: any; user: any; delegations: DelegationRule[] }
): { effective: string[]; mode: StageMode } {
  const ids: string[] = [];
  for (const sel of group.approvers) {
    let userId: string | null = null;
    if (sel.kind === "user") userId = sel.userId;
    else if (sel.kind === "field") userId = readPath(context.record, sel.path);
    else if (sel.kind === "role") userId = lookupByRole(sel.role);
    else if (sel.kind === "delegated") {
      const delegation = context.delegations.find((d) => d.userId === sel.backupForUserId);
      userId = delegation ? delegation.delegateTo : sel.backupForUserId;
    }
    if (userId) {
      // Apply active delegations
      const activeDel = context.delegations.find((d) =>
        d.userId === userId && isWithinDateRange(new Date(), d.validFrom, d.validTo)
      );
      ids.push(activeDel ? activeDel.delegateTo : userId);
    }
  }
  return { effective: Array.from(new Set(ids)), mode: group.mode };
}

/**
 * Determine whether a parallel approval stage can advance, and what
 * the outcome is (approved/rejected/pending).
 *
 * - mode "all": needs every approver to approve; any rejection short-circuits
 * - mode "any": first approval advances; all rejections needed to reject
 */
export function canAdvanceStage(
  stage: StageV2,
  decisions: Record<string, "approved" | "rejected">
): { ready: boolean; outcome: "approved" | "rejected" | "pending" } {
  const decisionList = Object.values(decisions);
  if (stage.approvers.mode === "all") {
    if (decisionList.some((d) => d === "rejected")) return { ready: true, outcome: "rejected" };
    if (
      decisionList.length === stage.approvers.approvers.length &&
      decisionList.every((d) => d === "approved")
    ) {
      return { ready: true, outcome: "approved" };
    }
  } else {  // any-of
    if (decisionList.some((d) => d === "approved")) return { ready: true, outcome: "approved" };
    if (
      decisionList.length === stage.approvers.approvers.length &&
      decisionList.every((d) => d === "rejected")
    ) {
      return { ready: true, outcome: "rejected" };
    }
  }
  return { ready: false, outcome: "pending" };
}

/**
 * Determine the next stage after the current one, honouring any
 * RoutingCondition on the current stage.
 */
export function nextStage(
  currentStage: StageV2,
  allStages: StageV2[],
  record: any
): StageV2 | null {
  const currentIdx = allStages.findIndex((s) => s.id === currentStage.id);
  if (currentStage.condition) {
    const matches = evalCondition(currentStage.condition.if, record);
    const targetId = matches
      ? currentStage.condition.then
      : (currentStage.condition.else ?? allStages[currentIdx + 1]?.id);
    return allStages.find((s) => s.id === targetId) ?? null;
  }
  return allStages[currentIdx + 1] ?? null;
}

/**
 * Simple expression evaluator for routing conditions.
 * Supports: `path OP value` where OP ∈ { ==, !=, >, <, >=, <= }
 * String values can be quoted with double quotes; numbers are parsed automatically.
 */
export function evalCondition(expr: string, record: any): boolean {
  const m = expr.match(/^(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$/);
  if (!m) return false;
  const left = readPath(record, m[1].trim());
  const op = m[2];
  let right: any = m[3].trim();
  if (right.startsWith('"') && right.endsWith('"')) right = right.slice(1, -1);
  else if (!isNaN(Number(right))) right = Number(right);
  switch (op) {
    case "==": return left == right;   // eslint-disable-line eqeqeq
    case "!=": return left != right;   // eslint-disable-line eqeqeq
    case ">":  return left > right;
    case "<":  return left < right;
    case ">=": return left >= right;
    case "<=": return left <= right;
  }
  return false;
}

/**
 * Execute multiple branches in parallel and wait for all to complete.
 */
async function executeParallelBranches(
  edges: WorkflowEdge[],
  workflow: WorkflowDefinition,
  ctx: WorkflowExecutionContext,
  depth: number = 0,
): Promise<void> {
  const branches = edges.map(async (edge) => {
    const nextNode = workflow.definition.nodes.find(
      (n) => n.id === edge.target,
    );
    if (nextNode) {
      // Each branch gets its own context copy to avoid mutation conflicts.
      //
      // CAREFUL: this spread copies `variables` by value (intended) but
      // everything else by reference. Anything that must accumulate
      // ACROSS branches has to be a reference type held on ctx —
      // `__stepBudget`, `__joinCounters`, `__completed`. Adding a plain
      // number or string here and expecting branches to share it is the
      // bug that let a forked cycle run until V8 aborted the process.
      const branchCtx = { ...ctx, variables: { ...ctx.variables } };
      await executeNode(nextNode, workflow, branchCtx, depth + 1);
      // Merge variables back
      Object.assign(ctx.variables, branchCtx.variables);
      ctx.log.push(...branchCtx.log.filter((e) => !ctx.log.includes(e)));
    }
  });

  await Promise.all(branches);
}

// Rule-table evaluation lives in ./decision.ts (kept out of engine.ts
// so the standalone test harness can exercise it without pulling in
// any @/db / drizzle imports).
