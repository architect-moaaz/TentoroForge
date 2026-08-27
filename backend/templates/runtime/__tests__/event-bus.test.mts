/**
 * R1/R3 event-layer tests — trigger matching, the emit_event node, and
 * the wait_for_event pause/resume cycle through the real engine.
 *
 * Bundled with esbuild (engine.ts imports ../feel-lite) then executed
 * with node — same harness as rule-set.test.mts. Run via
 *   __tests__/run-event-tests.sh
 * No DB: the emit_event node takes a mock emitter through its factory,
 * and wait_for_event's persistence is exercised at the engine seam
 * (pause result → process variables → resume input), exactly the state
 * that rides through workflow_tasks in a live app.
 */

import {
  getTriggerContract,
  findWorkflowsForEvent,
  buildResumeInput,
  buildTimeoutResumeInput,
  WAITING_EVENT_VAR,
} from "../events/triggers.ts";
import { makeEmitEventHandler } from "../events/emit-node.ts";
import { executeWorkflow, registerActionHandler } from "../workflows/engine.ts";

let passed = 0;
let failed = 0;

function assertEq<T>(actual: T, expected: T, name: string): void {
  const ok =
    actual === expected || JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    console.log(`  ✗ ${name}`);
    console.log(`      expected: ${JSON.stringify(expected)}`);
    console.log(`      actual:   ${JSON.stringify(actual)}`);
  }
}

// ── getTriggerContract / findWorkflowsForEvent ──────────────────────

console.log("getTriggerContract:");
const evWf = {
  id: "wf-ev",
  trigger: { kind: "event", event: "order.created" },
  definition: { trigger: { type: "manual" }, nodes: [], edges: [] },
};
const schedWf = {
  id: "wf-sched",
  trigger: { kind: "schedule", cron: "0 9 * * 1" },
  definition: { trigger: { type: "manual" }, nodes: [], edges: [] },
};
const manualWf = {
  id: "wf-manual",
  definition: { trigger: { type: "manual" }, nodes: [], edges: [] },
};
const legacyEvWf = {
  id: "wf-legacy",
  definition: { trigger: { type: "db_change", event: "invoice.paid" }, nodes: [], edges: [] },
};

assertEq(
  getTriggerContract(evWf),
  { kind: "event", event: "order.created" },
  "top-level event contract",
);
assertEq(
  getTriggerContract(schedWf),
  { kind: "schedule", cron: "0 9 * * 1" },
  "top-level schedule contract",
);
assertEq(getTriggerContract(manualWf), null, "manual workflow has no contract");
assertEq(
  getTriggerContract(legacyEvWf),
  { kind: "event", event: "invoice.paid" },
  "legacy definition.trigger db_change with dotted event normalises",
);
assertEq(
  getTriggerContract({ id: "x", trigger: { kind: "schedule", cron: "not a cron" } }),
  null,
  "invalid cron in contract is rejected",
);

console.log("findWorkflowsForEvent:");
const all = [evWf, schedWf, manualWf, legacyEvWf, evWf /* dupe (name-alias) */];
assertEq(
  findWorkflowsForEvent(all, "order.created").map((w) => w.id),
  ["wf-ev"],
  "matches the event workflow once (deduped by id)",
);
assertEq(
  findWorkflowsForEvent(all, "invoice.paid").map((w) => w.id),
  ["wf-legacy"],
  "legacy-shaped event workflow matches",
);
assertEq(
  findWorkflowsForEvent(all, "order.deleted").length,
  0,
  "no match for an unknown event",
);

// ── emit_event node (mock emitter) ──────────────────────────────────

console.log("emit_event node:");
{
  const emitted: Array<{ type: string; opts: any }> = [];
  const handler = makeEmitEventHandler({
    emit: async (type, opts) => {
      emitted.push({ type, opts });
      return { id: "evt-123" };
    },
  });
  const ctx = { variables: {}, input: {}, log: [] };
  const out = (await handler(
    {
      actionType: "emit_event",
      event: "order.flagged",
      payload: { reason: "fraud-check" },
      entity: "orders",
      entityId: "o-1",
    },
    ctx,
  )) as any;
  assertEq(out.emitted, true, "reports emitted:true");
  assertEq(out.eventId, "evt-123", "returns the inserted row id");
  assertEq(emitted.length, 1, "wrote exactly one event row");
  assertEq(emitted[0].type, "order.flagged", "row carries the event type");
  assertEq(
    emitted[0].opts,
    { entity: "orders", entityId: "o-1", payload: { reason: "fraud-check" } },
    "row carries entity/entityId/payload",
  );

  const failing = makeEmitEventHandler({
    emit: async () => {
      throw new Error("db down");
    },
  });
  const failOut = (await failing({ event: "x.y" }, ctx)) as any;
  assertEq(failOut.emitted, false, "bus failure → emitted:false");
  assertEq("error" in failOut, false, "no {error} key — the engine must NOT fail the run");
  assertEq(String(failOut.warning).includes("db down"), true, "warning carries the cause");

  const emptyOut = (await handler({ payload: {} }, ctx)) as any;
  assertEq(emptyOut.emitted, false, "empty config.event → emitted:false");
  assertEq(emitted.length, 1, "nothing extra written for the empty-event call");
}

// ── wait_for_event: pause, then resume on matching event ────────────

console.log("wait_for_event pause/resume:");
{
  const recorded: any[] = [];
  registerActionHandler("record_result", async (_config, ctx) => {
    recorded.push({ amount: ctx.variables.amount, orderId: ctx.variables.orderId });
    return { recorded: true };
  });

  const wf: any = {
    id: "wf-wait",
    name: "WaitDemo",
    processVariables: [{ name: "orderId", type: "string" }],
    definition: {
      trigger: { type: "api_event", event: "order_created" },
      nodes: [
        {
          id: "trigger",
          type: "trigger",
          data: { label: "Trigger", nodeType: "trigger", config: {} },
        },
        {
          id: "wait1",
          type: "action",
          data: {
            label: "Wait for payment",
            nodeType: "action",
            config: { actionType: "wait_for_event", event: "payment.received", timeoutMs: 120000 },
          },
        },
        {
          id: "after",
          type: "action",
          data: {
            label: "Record",
            nodeType: "action",
            config: { actionType: "record_result" },
          },
        },
        { id: "end", type: "end", data: { label: "Done", nodeType: "end" } },
      ],
      edges: [
        { id: "e1", source: "trigger", target: "wait1" },
        { id: "e2", source: "wait1", target: "after" },
        { id: "e3", source: "after", target: "end" },
      ],
    },
  };

  // 1. Fresh run pauses AT the wait node.
  const run1 = await executeWorkflow(wf, { orderId: "o-77" });
  assertEq(run1.status, "paused", "run pauses at wait_for_event");
  assertEq(run1.pausedAt, "wait1", "pausedAt names the wait node");
  assertEq((run1 as any).pendingTask?.taskType, "wait_for_event", "pendingTask taskType");
  assertEq((run1 as any).pendingTask?.dueIn, 2, "timeoutMs surfaces as dueIn minutes");
  assertEq(
    (run1.output as any)[WAITING_EVENT_VAR],
    "payment.received",
    "awaited event rides in process variables (→ workflow_tasks row)",
  );
  assertEq(recorded.length, 0, "downstream node did NOT run yet");

  // 2. Resume with the event payload — same input the bus builds from the
  //    persisted workflow_tasks row.
  const resumeInput = buildResumeInput(
    run1.output as Record<string, unknown>,
    "wait1",
    "payment.received",
    { amount: 42 },
  );
  assertEq(
    resumeInput[`__step_wait1_completed`],
    true,
    "resume input seeds the T5 completion marker",
  );
  assertEq(
    WAITING_EVENT_VAR in resumeInput,
    false,
    "resume input clears the awaited-event marker",
  );

  const run2 = await executeWorkflow(wf, resumeInput);
  assertEq(run2.status, "completed", "resumed run completes");
  assertEq(recorded.length, 1, "downstream node ran exactly once");
  assertEq(recorded[0], { amount: 42, orderId: "o-77" }, "event payload + original vars visible downstream");
  const replayed = run2.log.find((l: any) => l.nodeId === "wait1");
  assertEq(
    Boolean((replayed as any)?.skippedResume),
    true,
    "wait node was replayed via the T5 short-circuit, not re-executed",
  );

  // 3. A wait node with no event is a loud failure, not an eternal hang.
  const badWf = JSON.parse(JSON.stringify(wf));
  badWf.id = "wf-wait-bad";
  badWf.definition.nodes[1].data.config = { actionType: "wait_for_event" };
  const run3 = await executeWorkflow(badWf, {});
  assertEq(run3.status, "failed", "empty config.event fails the run");
  assertEq(
    String(run3.error ?? "").includes("config.event is empty"),
    true,
    "error names the missing config",
  );
}

// ── buildTimeoutResumeInput (REM-1: wait timeout auto-resume) ───────

console.log("buildTimeoutResumeInput:");
{
  const pv = { orderId: "o-1", [WAITING_EVENT_VAR]: "payment.received" };
  const input = buildTimeoutResumeInput(pv, "waitNode", "payment.received");
  assertEq(input["__step_waitNode_completed"], true, "wait node marked completed");
  assertEq(
    (input["__step_waitNode_output"] as any)?.timedOut,
    true,
    "wait node output carries timedOut:true",
  );
  assertEq(input.timedOut, true, "top-level timedOut marker for bindings");
  assertEq(input.orderId, "o-1", "stored process variables preserved");
  assertEq(
    WAITING_EVENT_VAR in input,
    false,
    "awaited-event marker consumed on timeout resume",
  );
  assertEq(input.event, "payment.received", "awaited event name still readable");
}
{
  const input = buildTimeoutResumeInput(null, "n1", "x.y");
  assertEq(input["__step_n1_completed"], true, "null process variables tolerated");
}

// ── result ──────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);


