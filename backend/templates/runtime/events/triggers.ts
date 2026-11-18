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
  | { kind: "schedule"; cron: string; timezone?: string; enabled?: boolean };

/** The marker a paused `wait` stores where a `wait_for_event` stores its
 *  event: the clock, not an event, picks it up. */
export const TIMER_EVENT = "__timer";

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
 * THE NAME A RECORD'S CHANGE GOES BY, FROM ITS TABLE. The Blueprint projects
 * a `db_change` trigger to the table's drizzle export name, lowercased
 * (`_trigger_contract`): `stage_events` → `stageEvents` → `stageevents.created`.
 * That is the table with its separators gone. The data engine named the event
 * after whatever the caller called the record instead — `create("Application")`
 * announced `application.created` to a process listening for
 * `applications.created`. Every writer names it from the table now: the data
 * engine and the workflow write steps alike.
 */
export function recordEventType(
  tableName: string,
  op: "created" | "updated" | "deleted",
): string {
  return eventTypeFor(recordEventSlug(tableName), op);
}

/** The table's name as a record event spells it (`stage_events` → `stageevents`). */
export function recordEventSlug(tableName: string): string {
  return String(tableName ?? "").replace(/[^a-z0-9]/gi, "").toLowerCase();
}

/**
 * The run variable — and the event payload field — that says which processes
 * led to a change. A process a record change started, writing records itself,
 * hands its own id on with every change it makes; the next event carries the
 * chain, and the run that event starts holds it here.
 */
export const EVENT_CHAIN_VAR = "__eventChain";

/** How many processes one change may set off, one after another. */
export const MAX_EVENT_CHAIN = 8;

/** The chain a run held when it started — the ids of the processes before it. */
export function eventChainOf(variables: Record<string, unknown> | null | undefined): string[] {
  const c = variables?.[EVENT_CHAIN_VAR];
  return Array.isArray(c) ? c.map((x) => String(x)).filter(Boolean) : [];
}

/** The chain a change made by `workflowId`'s run passes on. */
export function eventChainAfter(
  variables: Record<string, unknown> | null | undefined,
  workflowId: string | null | undefined,
): string[] {
  const chain = eventChainOf(variables);
  return workflowId ? [...chain, String(workflowId)] : chain;
}

/**
 * Why `workflowId` must not start from an event its chain says, or null.
 *
 * A PROCESS IS NOT STARTED BY ITS OWN CHANGES. One that runs when an
 * application is updated and updates that application would start itself
 * again for ever; one that leads, through others, back to itself would too.
 * It runs once per change a person (or a schedule, or an outside system)
 * made, and a chain of different processes stops at MAX_EVENT_CHAIN.
 */
export function eventChainRefusal(chain: unknown, workflowId: string): string | null {
  const ids = Array.isArray(chain) ? chain.map((x) => String(x)) : [];
  if (ids.includes(String(workflowId))) {
    return `${workflowId} was not started: this change came from its own run (${[...ids, workflowId].join(" → ")})`;
  }
  if (ids.length >= MAX_EVENT_CHAIN) {
    return `${workflowId} was not started: ${ids.length} processes in a row already followed from one change (${ids.join(" → ")})`;
  }
  return null;
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
      return { kind: "schedule", cron: t.cron.trim(),
               ...(typeof t.timezone === "string" && t.timezone.trim() ? { timezone: t.timezone.trim() } : {}),
               ...(t.enabled === false ? { enabled: false } : {}) };
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

/** What a run an event starts is given. */
export function eventRunInput(
  evt: { type: string; entity?: string | null; entity_id?: string | null; payload?: unknown },
): Record<string, unknown> {
  const payload =
    evt.payload && typeof evt.payload === "object" ? evt.payload : {};
  // THE RECORD'S OWN FIELDS UNDERNEATH. A process a record change starts
  // reads that record; one written before the build said `{{entity.f}}`
  // reads `{{categoryId}}`, and declares it required — Personal Finance's
  // "Generate Insight from Activity" was refused on every transaction for
  // "needs profileId, categoryId, date" (u8w3uw4j, 2026-10-21). They fill
  // only what the event does not already say.
  const record = (payload as any)?.entity;
  const fields: Record<string, unknown> =
    record && typeof record === "object" && !Array.isArray(record) ? { ...record } : {};
  delete fields.id;
  // Payload fields at the top level (so {{entity.id}}-style bindings
  // resolve), plus the event envelope for explicit reads.
  const input: Record<string, unknown> = {
    ...fields,
    ...payload,
    event: evt.type,
    entityType: evt.entity ?? undefined,
    entityId: evt.entity_id ?? (payload as any)?.entity?.id ?? undefined,
  };
  return input;
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

/**
 * Build the resume input for a `wait` whose time has come. The wait node's
 * cached output says the clock ended it (`waited: true`, the moment it
 * waited until), and the run continues downstream as whoever was running.
 */
export function buildTimerResumeInput(
  processVariables: Record<string, unknown> | null | undefined,
  nodeId: string,
  until: string,
): Record<string, unknown> {
  const pv = processVariables && typeof processVariables === "object" ? processVariables : {};
  const output = { waited: true, until };
  const input: Record<string, unknown> = {
    ...pv,
    [`__step_${nodeId}_completed`]: true,
    [`__step_${nodeId}_output`]: output,
  };
  delete input[WAITING_EVENT_VAR];
  return input;
}
