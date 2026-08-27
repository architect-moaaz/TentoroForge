/**
 * Trigger-contract helpers — pure functions shared by the event bus,
 * the scheduler, the cron route and the workflow engine.
 *
 * The trigger JSON contract (emitted by the Python translator when a plan
 * workflow declares an event/schedule trigger) is a TOP-LEVEL key on the
 * workflow JSON:
 *
 *   { "id": "...", "name": "...",
 *     "trigger": { "kind": "event",    "event": "order.created" },
 *     ...  OR  ...
 *     "trigger": { "kind": "schedule", "cron":  "0 9 * * 1" },
 *     "definition": { ... } }
 *
 * Legacy definitions carry only `definition.trigger.{type,event,schedule}`;
 * `getTriggerContract` normalises both shapes so callers have ONE view.
 *
 * Pure module: no imports beyond ./cron — standalone-testable.
 */

import { isValidCron } from "./cron";

export type TriggerContract =
  | { kind: "event"; event: string }
  | { kind: "schedule"; cron: string };

/**
 * The process-variable name a paused wait_for_event execution stores its
 * awaited event under. Written by engine.ts at pause time; it rides into
 * workflow_tasks.process_variables via persistPendingTask, and
 * processPendingEvents matches on `process_variables->>'__waiting_event'`.
 * Keep the literal in sync with engine.ts (which cannot import this
 * module's constant without making the engine test bundle heavier).
 */
export const WAITING_EVENT_VAR = "__waiting_event";

/** Canonical event type for a data-engine mutation: "<slug>.created" … */
export function eventTypeFor(
  entitySlug: string,
  op: "created" | "updated" | "deleted",
): string {
  return `${String(entitySlug).toLowerCase()}.${op}`;
}

/**
 * Read a workflow's trigger contract, tolerating both the new top-level
 * shape and the legacy `definition.trigger` shape. Returns null when the
 * workflow has no event/schedule trigger (manual / button workflows).
 */
export function getTriggerContract(wf: unknown): TriggerContract | null {
  const w = wf as Record<string, any> | null;
  if (!w || typeof w !== "object") return null;

  // New top-level contract wins.
  const t = w.trigger;
  if (t && typeof t === "object") {
    if (t.kind === "event" && typeof t.event === "string" && t.event.trim()) {
      return { kind: "event", event: t.event.trim() };
    }
    if (t.kind === "schedule" && typeof t.cron === "string" && isValidCron(t.cron)) {
      return { kind: "schedule", cron: t.cron.trim() };
    }
  }

  // Legacy: definition.trigger.{type,event,schedule}. Only shapes that
  // are unambiguously event/cron qualify — api_event dispatch and the
  // interval-approximated schedule sweep keep handling the rest.
  const legacy = w.definition?.trigger;
  if (legacy && typeof legacy === "object") {
    if (
      (legacy.type === "db_change" || legacy.type === "api_event") &&
      typeof legacy.event === "string" &&
      legacy.event.includes(".")
    ) {
      return { kind: "event", event: legacy.event.trim() };
    }
    if (legacy.type === "schedule" && typeof legacy.cron === "string" && isValidCron(legacy.cron)) {
      return { kind: "schedule", cron: legacy.cron.trim() };
    }
  }
  return null;
}

/** All workflows (deduped by id) whose event trigger matches `eventType`. */
export function findWorkflowsForEvent<T extends { id?: string }>(
  workflows: Iterable<T>,
  eventType: string,
): T[] {
  const out: T[] = [];
  const seen = new Set<string>();
  for (const wf of workflows) {
    const id = String((wf as any)?.id ?? "");
    if (id && seen.has(id)) continue;
    if (id) seen.add(id);
    const trig = getTriggerContract(wf);
    if (trig?.kind === "event" && trig.event === eventType) out.push(wf);
  }
  return out;
}

/**
 * Build the resume input for an execution paused on a wait_for_event node.
 *
 * EXACTLY mirrors the human-task resume path in
 * /api/workflows/[id]/execute: stored process_variables first, then the
 * event payload, then the completion markers — the engine's T5
 * resume-idempotency short-circuit replays every already-completed node
 * (including the wait node itself, whose cached output is the event) and
 * continues downstream.
 */
export function buildResumeInput(
  processVariables: Record<string, unknown> | null | undefined,
  nodeId: string,
  eventType: string,
  eventPayload: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const pv = processVariables && typeof processVariables === "object" ? processVariables : {};
  const payload = eventPayload && typeof eventPayload === "object" ? eventPayload : {};
  const output = { event: eventType, ...payload };
  const input: Record<string, unknown> = {
    ...pv,
    ...payload,
    event: eventType,
    [`__step_${nodeId}_completed`]: true,
    [`__step_${nodeId}_output`]: output,
  };
  // The awaited-event marker is consumed — a later wait node writes its own.
  delete input[WAITING_EVENT_VAR];
  return input;
}

/**
 * Build the resume input for a wait_for_event node whose timeout elapsed
 * (workflow_tasks.due_at passed with no matching event). Identical to
 * buildResumeInput, but the wait node's cached output carries
 * `timedOut: true` and NO event payload — downstream Conditional nodes
 * branch on `{{<node>.timedOut}}` to take the escalation path.
 */
export function buildTimeoutResumeInput(
  processVariables: Record<string, unknown> | null | undefined,
  nodeId: string,
  awaitedEvent: string,
): Record<string, unknown> {
  const pv = processVariables && typeof processVariables === "object" ? processVariables : {};
  const output = { event: awaitedEvent, timedOut: true };
  const input: Record<string, unknown> = {
    ...pv,
    event: awaitedEvent,
    timedOut: true,
    [`__step_${nodeId}_completed`]: true,
    [`__step_${nodeId}_output`]: output,
  };
  delete input[WAITING_EVENT_VAR];
  return input;
}
