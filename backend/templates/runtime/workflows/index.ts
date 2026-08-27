/**
 * Workflow runtime — public API for generated apps.
 *
 * Usage in a Next.js API route:
 * ```ts
 * import { triggerWorkflow, registerDefaultActions } from "@/lib/workflows";
 *
 * registerDefaultActions(); // run once at boot
 *
 * export async function POST(req: Request) {
 *   const body = await req.json();
 *   const result = await triggerWorkflow("SurveyCreated", { surveyId: body.id });
 *   return Response.json(result);
 * }
 * ```
 */

import { promises as fs } from "fs";
import path from "path";
// The app's data layer — used by the default db_* action handlers so workflows
// actually read/write the database. Every generated app emits these.
import { db } from "@/db";
import * as schema from "@/db/schema";
import { getTableName, is, Table, eq, and, sql } from "drizzle-orm";
// Self-heal integration — every catch site below reports the failure to
// Forge so Smith can pick it up and edit the offending file directly.
// Fire-and-forget: a report failure never crashes the caller.
import { reportFromError } from "@/lib/error_reporter";
// FK-role authority — auto-fill an ACTOR FK from the acting user, never a `domain`
// FK (target != users). Absent-table (registry-less app) → legacy name fallback.
import { FK_ROLES, fkRole, isDomainFk } from "../fk-roles";
import {
  executeWorkflow,
  registerActionHandler,
  getActionHandler,
} from "./engine";
import { registerAIActions } from "./ai";
import { registerOcrActions } from "./ocr";
// emit_event node factory — pure module; the durable bus (events/bus.ts)
// is injected lazily below so loading the workflow runtime never drags in
// the event tables on apps that predate them.
import { makeEmitEventHandler } from "../events/emit-node";
import { evaluateExpression } from "../feel-lite";
import type {
  WorkflowDefinition,
  WorkflowExecutionResult,
  WorkflowExecutionContext,
  ActionHandler,
  NodeConfig,
} from "./types";

export {
  executeWorkflow,
  registerActionHandler,
  getActionHandler,
} from "./engine";

export type {
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  WorkflowExecutionContext,
  WorkflowExecutionResult,
  ExecutionLogEntry,
  NodeConfig,
  ActionHandler,
  TriggerType,
  ActionType,
  NodeType,
} from "./types";

/**
 * Workflow definition cache — loads JSONs from /workflows/ directory once.
 */
const workflowCache: Map<string, WorkflowDefinition> = new Map();
let workflowsLoaded = false;

/**
 * Load all workflow definitions from the project's /workflows/ directory.
 * Caches in memory after first load.
 */
export async function loadWorkflows(
  workflowsDir?: string,
): Promise<Map<string, WorkflowDefinition>> {
  if (workflowsLoaded) return workflowCache;

  const dir = workflowsDir || path.join(process.cwd(), "workflows");

  let files: string[] = [];
  try {
    files = await fs.readdir(dir);
  } catch {
    // No workflows directory — that's fine, no workflows defined.
    workflowsLoaded = true;
    return workflowCache;
  }
  // Per-file try/catch: a single malformed workflow JSON used to throw
  // out of the readdir loop and mark loading complete — so every later
  // triggerWorkflow lookup returned "Workflow not found" for perfectly
  // valid siblings. Isolate each file. See workflow-audit gap #9.
  for (const file of files) {
    if (!file.endsWith(".json")) continue;
    try {
      const content = await fs.readFile(path.join(dir, file), "utf-8");
      const definition = JSON.parse(content) as WorkflowDefinition;
      workflowCache.set(definition.id, definition);
      workflowCache.set(definition.name, definition);
    } catch (err) {
      console.warn(`[workflow] failed to load ${file}:`, err);
    }
  }
  workflowsLoaded = true;

  return workflowCache;
}

/**
 * Trigger a workflow by ID or name.
 *
 * @param workflowIdOrName Workflow ID (e.g., "3a5997fb") or name (e.g., "SurveyCreated")
 * @param input Trigger payload (passed as ctx.input and ctx.variables)
 * @param user Optional user context for permission-aware actions
 */
export async function triggerWorkflow(
  workflowIdOrName: string,
  input: Record<string, unknown> = {},
  user?: WorkflowExecutionContext["user"],
): Promise<WorkflowExecutionResult> {
  await loadWorkflows();

  const workflow = workflowCache.get(workflowIdOrName);
  if (!workflow) {
    return {
      workflowId: workflowIdOrName,
      workflowName: workflowIdOrName,
      startedAt: new Date().toISOString(),
      completedAt: new Date().toISOString(),
      status: "failed",
      log: [],
      output: {},
      error: `Workflow not found: ${workflowIdOrName}`,
    };
  }

  const result = await executeWorkflow(workflow, input, user);
  await persistPendingTask(result, workflowIdOrName, input, user);
  return result;
}

/**
 * Persist a task row when a workflow pauses at an approval/user_task node.
 *
 * Any entry point that starts a workflow (the /execute route, an event-registry
 * data event, a manual trigger) funnels through here so a pending task always
 * exists for the assignee to resolve — previously only the /execute route
 * persisted, so event-started workflows paused with no task to act on.
 * Best-effort: the workflow_tasks table may not exist yet — never throw.
 */
// Dynamic assignment. Menu of strategies (Slice E T3):
//  • static             → task.assignee wins
//  • role               → any user with that role (runtime falls back to role)
//  • round_robin        → rotate by count of prior tasks in the pool
//  • load_balanced      → pool member with fewest open (pending) tasks
//  • creator            → the user who kicked off the workflow
//  • entity_field       → a FK column on the entity row (e.g. Candidate.assignedRecruiterId)
//  • reporting_manager  → one level up the org chart (users.manager_id)
//  • department_head    → the user with role=X in the same department as the entity
//  • group              → members of a named group (user_groups.group_name → round-robin)
// The Python side (services.task_assignment_strategies) mirrors this
// menu exactly — the planner, guards, and this runtime must all
// recognize the same strategy names.
async function _resolveAssignee(
  task: any,
  input: Record<string, unknown> = {},
  user?: { id?: string; role?: string; email?: string } | undefined,
): Promise<{ assignee: any; role: any }> {
  const strategy = task.assignmentStrategy;
  const role = task.assigneeRole || null;
  const fallback = { assignee: task.assignee || role || "admin", role };
  if (!strategy) return fallback;

  const entity = (input.entity as Record<string, unknown> | undefined) ?? {};
  const anchorUserId =
    (input.startedBy as string | undefined) ??
    user?.id ??
    (task.startedBy as string | undefined);

  // ─── creator ────────────────────────────────────────────────────────
  if (strategy === "creator") {
    return anchorUserId
      ? { assignee: String(anchorUserId), role }
      : fallback;
  }

  // ─── entity_field ───────────────────────────────────────────────────
  if (strategy === "entity_field") {
    const field = task.assignmentField as string | undefined;
    if (field) {
      const raw =
        (entity as any)[field] ??
        (input as any)[field] ??
        (input as any)[`${field}Id`];
      if (raw !== undefined && raw !== null && String(raw) !== "") {
        return { assignee: String(raw), role };
      }
    }
    return fallback;
  }

  // ─── reporting_manager ─────────────────────────────────────────────
  if (strategy === "reporting_manager") {
    if (!anchorUserId) return fallback;
    try {
      const res: any = await db.execute(sql`
        SELECT manager_id AS id FROM users WHERE id = ${String(anchorUserId)}
      `);
      const managerId = ((res?.rows ?? res) as any[])?.[0]?.id;
      if (managerId) return { assignee: String(managerId), role };
    } catch { /* users.manager_id may not exist — fall through */ }
    return fallback;
  }

  // ─── department_head ───────────────────────────────────────────────
  if (strategy === "department_head") {
    const dept = (entity as any).departmentId ?? (input as any).departmentId;
    if (!role || !dept) return fallback;
    try {
      const res: any = await db.execute(sql`
        SELECT id FROM users WHERE role = ${String(role)}
          AND department_id = ${String(dept)} LIMIT 1
      `);
      const uid = ((res?.rows ?? res) as any[])?.[0]?.id;
      if (uid) return { assignee: String(uid), role };
    } catch { /* users.department_id may not exist */ }
    return fallback;
  }

  // ─── group (round-robin across group members) ──────────────────────
  if (strategy === "group") {
    const groupName = task.assigneeGroup as string | undefined;
    if (!groupName) return fallback;
    try {
      const res: any = await db.execute(sql`
        SELECT user_id AS id FROM user_groups WHERE group_name = ${groupName}
      `);
      const members = ((res?.rows ?? res) as any[]).map((r) => String(r.id));
      if (members.length) {
        // Rotate by prior task count so no one member is drained first.
        const counts: any = await db.execute(sql`
          SELECT COUNT(*)::int AS c FROM workflow_tasks
          WHERE assignee_id = ANY(${members})
        `);
        const total = Number(((counts?.rows ?? counts) as any[])?.[0]?.c ?? 0);
        return { assignee: members[total % members.length], role };
      }
    } catch { /* user_groups table may not exist */ }
    return fallback;
  }

  // ─── round_robin / load_balanced (pool-based) ──────────────────────
  if (strategy !== "round_robin" && strategy !== "load_balanced") return fallback;

  let candidates: string[] = Array.isArray(task.assigneePool) ? task.assigneePool.map(String) : [];
  try {
    if (!candidates.length && role) {
      const res: any = await db.execute(sql`SELECT id FROM users WHERE role = ${role}`);
      candidates = ((res?.rows ?? res) as any[]).map((r) => String(r.id));
    }
  } catch { /* users table may not have a role column — fall through */ }
  if (!candidates.length) return fallback;

  try {
    if (strategy === "load_balanced") {
      const res: any = await db.execute(sql`
        SELECT assignee_id, COUNT(*)::int AS c FROM workflow_tasks
        WHERE status = 'pending' AND assignee_id = ANY(${candidates}) GROUP BY assignee_id`);
      const counts = new Map<string, number>(candidates.map((c) => [c, 0]));
      for (const r of (res?.rows ?? res) as any[]) counts.set(String(r.assignee_id), Number(r.c));
      let best = candidates[0], min = Infinity;
      for (const c of candidates) { const n = counts.get(c) ?? 0; if (n < min) { min = n; best = c; } }
      return { assignee: best, role };
    }
    const res: any = await db.execute(sql`
      SELECT COUNT(*)::int AS c FROM workflow_tasks WHERE assignee_id = ANY(${candidates})`);
    const total = Number(((res?.rows ?? res) as any[])?.[0]?.c ?? 0);
    return { assignee: candidates[total % candidates.length], role };
  } catch {
    return { assignee: candidates[0], role };
  }
}

export async function persistPendingTask(
  result: WorkflowExecutionResult,
  workflowId: string,
  input: Record<string, unknown> = {},
  user?: WorkflowExecutionContext["user"],
): Promise<void> {
  if (result.status !== "paused" || !(result as any).pendingTask) return;
  const task = (result as any).pendingTask;
  const { assignee: _assignee, role: _role } = await _resolveAssignee(task, input, user);
  const entityId =
    (input.entityId as string) ??
    ((input.entity as any)?.id as string) ??
    (input.id as string) ??
    "";
  const entityType = (input.entityType as string) ?? "";

  // Escalation policy: prefer the pendingTask's carry-through, fall
  // back to the same key on the raw output. Empty policy means no
  // escalation node fired upstream — leave escalate_to null and let
  // due_at come from `task.dueIn` (SLA minutes on the task node
  // itself).
  const escalation =
    (task.escalationPolicy as { slaHours?: number; escalateTo?: string } | undefined) ??
    (result.output as any)?.__escalationPolicy;
  const slaHours = escalation?.slaHours;
  const escalateTo = escalation?.escalateTo || null;
  // Compute due_at: escalation SLA (hours) wins; else the task's own
  // dueIn (minutes) — matches the pre-existing behavior.
  const dueAt =
    slaHours && slaHours > 0
      ? new Date(Date.now() + slaHours * 3600_000).toISOString()
      : task.dueIn
        ? new Date(Date.now() + task.dueIn * 60_000).toISOString()
        : null;

  try {
    await db.execute(sql`
      INSERT INTO workflow_tasks (
        id, workflow_id, workflow_instance_id, node_id, node_label,
        task_type, status, assignee_id, assignee_role, assignee_group_id,
        entity_type, entity_id, form_data, form_binding, process_variables,
        due_at, escalate_to, created_at
      ) VALUES (
        gen_random_uuid(),
        ${workflowId},
        gen_random_uuid(),
        ${task.nodeId || ""},
        ${task.nodeLabel || ""},
        ${task.taskType || "user_task"},
        'pending',
        ${_assignee || null},
        ${_role || null},
        ${null},
        ${entityType},
        ${entityId},
        ${JSON.stringify(result.output || {})},
        ${JSON.stringify(task.formBinding || {})},
        ${JSON.stringify(result.output || {})},
        ${dueAt},
        ${escalateTo},
        NOW()
      )
    `);
  } catch (err) {
    console.warn("[workflow] Could not persist task:", err);
  }
}

/**
 * Trigger workflows by event name (api_event triggers).
 * Looks up all workflows whose trigger.event matches and runs them.
 */
export async function triggerWorkflowEvent(
  eventName: string,
  input: Record<string, unknown> = {},
  user?: WorkflowExecutionContext["user"],
): Promise<WorkflowExecutionResult[]> {
  await loadWorkflows();

  const matching: WorkflowDefinition[] = [];
  const seen = new Set<string>();

  for (const workflow of workflowCache.values()) {
    if (seen.has(workflow.id)) continue;
    seen.add(workflow.id);

    const trigger = workflow.definition.trigger;
    if (
      trigger.type === "api_event" &&
      (trigger.event === eventName || workflow.name === eventName)
    ) {
      matching.push(workflow);
    }
  }

  return Promise.all(
    matching.map(async (w) => {
      const result = await executeWorkflow(w, input, user);
      await persistPendingTask(result, w.id, input, user);
      return result;
    }),
  );
}

/**
 * List all loaded workflow definitions (for debugging / UI).
 */
export async function listWorkflows(): Promise<WorkflowDefinition[]> {
  await loadWorkflows();
  // Dedupe by ID since we cache by both ID and name
  const seen = new Set<string>();
  const unique: WorkflowDefinition[] = [];
  for (const w of workflowCache.values()) {
    if (!seen.has(w.id)) {
      seen.add(w.id);
      unique.push(w);
    }
  }
  return unique;
}

// ---------------------------------------------------------------------------
// Default action handlers — generated apps can override these
// ---------------------------------------------------------------------------

/**
 * Register default no-op handlers so workflows don't crash if no handlers
 * are registered. Generated apps should call registerDefaultActions() then
 * override with real implementations (db_query → drizzle, send_email → SMTP, etc.)
 */
// --- db action helpers -----------------------------------------------------
// Resolve a Drizzle table object by its SQL table name (config.table), since
// the schema export name (camelCase) may differ from the table name (snake).
// Canonicalise a table name so snake_case, camelCase and kebab-case variants of
// the same name all match: "knowledge_articles" == "knowledgeArticles" ==
// "knowledge-articles". Generators don't all agree on casing (the schema uses a
// camelCase pgTable name, the workflow generator emits snake_case), and
// single-word tables ("tickets") hid the split — multi-word entities expose it.
function _canonTable(s: string): string {
  return s.toLowerCase().replace(/[_-]/g, "");
}

function _resolveTable(name?: unknown): any {
  if (typeof name !== "string") return undefined;
  const tables = Object.values(schema as Record<string, unknown>).filter(
    (v) => is(v as any, Table),
  );
  // Exact match first (fast path, and unambiguous).
  for (const v of tables) {
    if (getTableName(v as any) === name) return v;
  }
  // Tolerant match: ignore case + separators so snake/camel/kebab variants of
  // the same table resolve instead of throwing "unknown table".
  const target = _canonTable(name);
  for (const v of tables) {
    if (_canonTable(getTableName(v as any)) === target) return v;
  }
  return undefined;
}

// Walk a dotted + bracket-indexed path against a root object. Handles:
//   "a.b"         → root.a.b
//   "a.b[0].c"    → root.a.b[0].c
//   "arr[2]"      → root.arr[2]
//   "arr[0][1]"   → root.arr[0][1]
// Returns undefined on any missing / null segment (never throws). Whitespace
// inside indices is not permitted (a real binding never has it) so we don't
// tolerate it — the regex catches malformed refs by falling out.
function _walkPath(root: unknown, path: string): unknown {
  if (root == null) return undefined;
  // Split "a.b[0].c" into ["a", "b", 0, "c"]. `\d+` inside `[]` becomes a
  // numeric index; anything else terminates the walk (defensive against
  // pathological input that slipped past the regex above).
  const parts: (string | number)[] = [];
  const re = /([A-Za-z_][\w]*)|\[(\d+)\]/g;
  let m: RegExpExecArray | null;
  let consumed = 0;
  while ((m = re.exec(path)) !== null) {
    // Ensure the regex matched contiguously — the input between tokens can
    // only be a single "." separator. Anything else (like whitespace, a
    // stray character) means the path is malformed.
    if (m.index !== consumed && !(m.index === consumed + 1 && path[consumed] === ".")) {
      return undefined;
    }
    if (m[1] !== undefined) parts.push(m[1]);
    else if (m[2] !== undefined) parts.push(Number(m[2]));
    consumed = m.index + m[0].length;
  }
  if (consumed !== path.length) return undefined;
  let cur: any = root;
  for (const seg of parts) {
    if (cur == null) return undefined;
    cur = cur[seg as any];
  }
  return cur;
}

// A config value is either a process-variable name, a special token, or a
// literal. `{{var}}` templates interpolate from the workflow variables.
function _resolveRef(ref: unknown, ctx: WorkflowExecutionContext): unknown {
  if (typeof ref !== "string") return ref;
  // Canonical runtime sentinels — kept in sync with services/proof_auto_heal.py.
  // `$now` and `$today` are the forward names planner + auto-heal both use.
  // CURRENT_TIMESTAMP / NOW() are retained as backwards-compat aliases.
  if (ref === "$now" || ref === "CURRENT_TIMESTAMP" || ref === "NOW()") return new Date();
  if (ref === "$today") {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }
  if (ref === "$user.id") return (ctx as any)?.user?.id ?? ctx.variables?.__user?.id ?? ctx.variables?.user?.id ?? null;
  if (ref === "true") return true;
  if (ref === "false") return false;
  if (ref.includes("{{")) {
    // SOLE-TEMPLATE SHORT-CIRCUIT: when the string is a single `{{path}}`
    // with nothing else around it, return the RAW resolved value (object,
    // number, array, boolean) — not a stringified form. Critical for jsonb
    // column writes: without this, `values.extractedFields = "{{ai.data}}"`
    // becomes the string `"[object Object]"` and the DB gets garbage. The
    // interpolated branch below still runs when the template is embedded
    // in surrounding text ("Hello {{name}}") — that must coerce to string.
    const soleMatch = ref.match(/^\s*\{\{\s*([\w.[\]]+)\s*\}\}\s*$/);
    if (soleMatch) {
      const key = soleMatch[1];
      const v: unknown = ctx.variables[key];
      if (v !== undefined) return v;
      if (!key.includes(".") && !key.includes("[")) return "";
      return _walkPath(ctx.variables, key);
    }
    // Accept dotted paths PLUS bracket-index segments: `search.result.data.web[0].url`.
    // Feel-lite (used elsewhere for expressions) refuses `[` in identifier
    // paths — but a workflow binding is a walk, not an expression, so route
    // it through the walker directly. Mirrors packages/renderer/src/runtime
    // BIND-FIX #211 which fixed the same class of failure in the UI layer.
    return ref.replace(/\{\{\s*([\w.[\]]+)\s*\}\}/g, (_m, k) => {
      const key = k as string;
      // Fast path: flat lookup, then bracket-free dot-walk (legacy behaviour
      // for producers already writing dotted keys as-is).
      let v: unknown = ctx.variables[key];
      if (v !== undefined) return v == null ? "" : String(v);
      if (!key.includes(".") && !key.includes("[")) return "";
      const walked = _walkPath(ctx.variables, key);
      return walked == null ? "" : String(walked);
    });
  }
  if (Object.prototype.hasOwnProperty.call(ctx.variables, ref)) return ctx.variables[ref];
  return ref; // literal
}

// Drizzle timestamp columns expect a Date, not a string. Coerce ISO
// date/datetime strings so db_insert/db_update don't blow up on
// `value.toISOString is not a function`.
const _ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$/;
// Plausible epoch range: 2001-01-01 to 2100-01-01 in millis. Rules out small
// integers that happen to appear in user data (age, count, order-id) — those
// stay as-is so numeric columns still get numbers.
const _EPOCH_MIN_MS = 978307200000;
const _EPOCH_MAX_MS = 4102444800000;

/**
 * Does this Drizzle column actually hold a date/time?
 *
 * Reads `dataType` ("date") or `columnType` ("PgTimestamp", "PgDate", …).
 * Returns `undefined` when the column carries no type information at all,
 * which the caller treats as "unknown" rather than "not a date".
 */
function _isDateColumn(col: unknown): boolean | undefined {
  if (!col || typeof col !== "object") return undefined;
  const c = col as { dataType?: unknown; columnType?: unknown };
  if (typeof c.dataType === "string") return c.dataType === "date";
  if (typeof c.columnType === "string") return /date|timestamp/i.test(c.columnType);
  return undefined;
}

function _isIntColumn(col: unknown): boolean {
  if (!col || typeof col !== "object") return false;
  const c = col as { dataType?: unknown; columnType?: unknown };
  if (typeof c.columnType === "string") return /^Pg(Integer|BigInt|Small|Serial|BigSerial)/i.test(c.columnType);
  if (typeof c.dataType === "string") return c.dataType === "number";
  return false;
}

function _coerceValue(v: unknown, col?: unknown): unknown {
  // An empty form field arrives as "" — Postgres rejects that for non-text
  // columns ("invalid input syntax for type integer/uuid: \"\""). Treat a blank
  // optional field as NULL.
  if (v === "") return null;
  // Float → int coercion for integer columns. Firecrawl / AI extractors
  // routinely return prices as `479.99` even when the column is INTEGER
  // (whole-dollars convention on retail apps). Postgres rejects with
  // `invalid input syntax for type integer: "479.99"` and takes down the
  // whole workflow. Rounding is safe here because the column author
  // chose INT and wanted the fractional part discarded. Never coerce when
  // the column type is unknown — a text column that happens to hold "1.5"
  // stays "1.5", not "2".
  if (typeof v === "number" && !Number.isInteger(v) && _isIntColumn(col)) {
    return Math.round(v);
  }
  // Same coercion for numeric strings ("479.99") heading into int columns.
  if (typeof v === "string" && /^-?\d+\.\d+$/.test(v) && _isIntColumn(col)) {
    const n = Number(v);
    if (!isNaN(n)) return Math.round(n);
  }
  // Already a Date — pass through.
  if (v instanceof Date) return v;
  // ISO date string → Date (existing DL-1 behaviour).
  if (typeof v === "string" && _ISO_DATE.test(v)) {
    // Only coerce when the column actually holds a date.
    //
    // This used to convert ANY ISO-shaped string wherever it was going.
    // Real text values collide with that shape constantly — invoice
    // numbers, SKUs, contract references, version tags, and any field a
    // user happens to fill with "2026-01-01". Sent to a text column the
    // Date is stringified by the driver in the server's locale/timezone,
    // so "2026-01-01" lands as "Thu Jan 01 2026 00:00:00 GMT+0530", or
    // shifts to the previous day in UTC. The write SUCCEEDS, so nothing
    // ever reported it.
    //
    // `undefined` means the column carries no type metadata (an older
    // generated app, or a value not bound to a column at all). Coerce in
    // that case, preserving the original behaviour — the reason this
    // function exists is that a Drizzle timestamp column rejects a
    // string outright, and that hard failure is worse than the silent
    // rewrite we are fixing.
    if (_isDateColumn(col) !== false) {
      const d = new Date(v);
      if (!isNaN(d.getTime())) return d;
    }
  }
  // Epoch-millis number in plausible range → Date. Guards against drizzle
  // calling `.toISOString()` on a numeric timestamp (which crashes the whole
  // insert). Small integers (age, count) stay as numbers.
  if (typeof v === "number" && v >= _EPOCH_MIN_MS && v <= _EPOCH_MAX_MS) {
    const d = new Date(v);
    if (!isNaN(d.getTime())) return d;
  }
  return v;
}

function _resolveMap(map: unknown, ctx: WorkflowExecutionContext): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (map && typeof map === "object") {
    for (const [field, ref] of Object.entries(map as Record<string, unknown>)) {
      out[field] = _coerceValue(_resolveRef(ref, ctx));
    }
  }
  return out;
}

// Like _resolveMap but for INSERT/UPDATE values: a `field -> processVar` mapping
// whose var the form didn't supply must be OMITTED, not inserted as the literal
// var-name string (which crashes typed columns, e.g. "landlordId" into a uuid).
const _BARE_IDENT = /^[A-Za-z_]\w*$/;
const _VALUE_TOKENS = ["CURRENT_TIMESTAMP", "NOW()", "true", "false"];

/**
 * Is this bare identifier an UNRESOLVED VARIABLE REFERENCE, or a LITERAL?
 *
 * The untyped `values` map conflates the two — `{status: "Rejected"}` and
 * `{landlordId: "landlordId"}` are both bare identifiers absent from
 * ctx.variables. This used to be decided by the string's SHAPE: anything
 * matching /^\w+$/ was dropped. The cost was that a genuine one-word
 * literal — which is what almost every status write is — was silently
 * deleted from the INSERT while the run reported success, and the
 * behaviour was whitespace-dependent ("Not Started" wrote, "Rejected"
 * vanished), which made it near-impossible to diagnose from outside.
 *
 * The workflow's own `processVariables` declaration is the only real
 * authority for which names are variables, so consult that first. Real
 * generated workflows always declare them (the CRUD generator and the
 * step translator both emit the list).
 *
 * When a workflow declares nothing we genuinely cannot tell, so keep the
 * conservative behaviour: omit. Dropping a value is recoverable and
 * visible in the log; writing a variable NAME into a uuid/int column is
 * a hard Postgres error on every row.
 */
function _isUnresolvedRef(ref: string, ctx: WorkflowExecutionContext): boolean {
  if (!_BARE_IDENT.test(ref)) return false;
  if (Object.prototype.hasOwnProperty.call(ctx.variables, ref)) return false;
  if (_VALUE_TOKENS.includes(ref)) return false;

  const declared: Set<string> | undefined = (ctx as any).__declaredVars;
  if (declared && declared.size > 0) {
    // We have a declaration: it is a reference only if it names a
    // declared process variable. Anything else is a literal.
    return declared.has(ref);
  }
  // No declaration — treat as LITERAL. Real refs always use `{{name}}`
  // (which never reaches this function because _resolveRef handles them).
  // The prior "conservative" default of `true` silently DROPPED every
  // one-word literal — `{status: "processing"}` vanished from every INSERT
  // and downstream nodes saw NULL for the column. Preferring literal means
  // a mis-typed identifier writes a bad value that Postgres rejects loudly,
  // which is diagnosable — the silent NULL wasn't.
  return false;
}

function _resolveValueMap(
  map: unknown,
  ctx: WorkflowExecutionContext,
  table?: any,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (map && typeof map === "object") {
    for (const [field, ref] of Object.entries(map as Record<string, unknown>)) {
      if (typeof ref === "string" && _isUnresolvedRef(ref, ctx)) {
        // Omitting used to be completely silent, so a write that lost half
        // its columns looked identical to one that succeeded. Say so.
        console.warn(
          `[workflow] value for column "${field}" omitted — process variable ` +
          `"${ref}" was declared but never supplied by the trigger input. ` +
          `The row will be written WITHOUT this column.`,
        );
        continue;
      }
      out[field] = _coerceValue(_resolveRef(ref, ctx), table?.[field]);
    }
  }
  return out;
}

// Legacy name-based owner/actor FK heuristics — used ONLY as a fallback when the
// insert target is absent from the FK-role authority (registry-less app). The
// authoritative path below reads the column's ROLE instead, so a domain FK
// (e.g. pets.ownerId → owners) is never mistaken for a user-ownership marker.
const _LEGACY_OWNER_FKS = ["landlordId", "ownerId", "userId", "createdById", "authorId"];
const _LEGACY_OWNER_FK_RE =
  /^(recruiter|owner|user|author|creator|assignee|assigned_?to|reviewer|approver|actor|(created|updated|submitted|requested|uploaded|reported|posted)_?by)_?id$/i;

// Drop keys the table doesn't have or that are empty "" / undefined (so they don't
// clobber DB defaults or crash type coercion, e.g. "" into a timestamp), and default
// an ACTOR FK to the acting user when missing.
function _finalizeInsert(
  table: any, values: Record<string, unknown>, ctx: WorkflowExecutionContext,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(values)) {
    if (!(k in table) || v === "" || v === undefined) continue;
    // Drizzle timestamp columns crash with "value.toISOString is not a
    // function" when they receive anything that isn't a Date (or null).
    // Detect the column type via drizzle's internal `columnType` /
    // `dataType` (both are set on all pg column builders) and coerce
    // best-effort. If we can't coerce, DROP the field so the column
    // default fires — much better than crashing the whole insert.
    const col = (table as any)[k];
    const colType = col && (col.columnType || col.dataType);
    const isTimestampCol = typeof colType === "string" &&
      /timestamp|date|time/i.test(colType);
    if (isTimestampCol && !(v instanceof Date) && v !== null) {
      const coerced = _coerceValue(v);
      if (coerced instanceof Date) {
        out[k] = coerced;
      } else {
        // Uncoercible into Date — drop rather than crash. Log so the
        // author sees the field name and can fix the workflow config.
        console.warn(
          `[workflow] db_insert: dropping ${k} — not Date-coercible (type=${typeof v}, value=${JSON.stringify(v)?.slice(0,80)}). Column default will fire.`,
        );
      }
      continue;
    }
    out[k] = v;
  }
  const uid = (ctx as { user?: { id?: unknown } }).user?.id;
  if (uid) {
    const tableName = getTableName(table);
    if (tableName in FK_ROLES) {
      // Role authority present — fill ONLY actor columns, never a domain FK.
      for (const col of Object.keys(table)) {
        if (out[col] != null) continue;
        if (isDomainFk(tableName, col)) continue;
        if (fkRole(tableName, col) === "actor") out[col] = uid;
      }
    } else {
      // No authority for this table (registry-less app) — legacy name-based fill.
      for (const fk of _LEGACY_OWNER_FKS) {
        if (fk in table && out[fk] == null) out[fk] = uid;
      }
      for (const col of Object.keys(table)) {
        if (out[col] == null && _LEGACY_OWNER_FK_RE.test(col)) out[col] = uid;
      }
    }
  }
  return out;
}

function _buildWhere(
  table: any, where: unknown, ctx: WorkflowExecutionContext,
  opts: { strict?: boolean } = { strict: true },
): any {
  if (!where || typeof where !== "object") return undefined;
  const entries = Object.entries(where as Record<string, unknown>);
  // Track which fields drifted from the schema so the error surfaces the
  // exact name(s) — snake_case↔camelCase drift and renamed columns are
  // the two failure modes we're catching here.
  const dropped: string[] = [];
  const emptyRefs: string[] = [];
  const conds = entries
    .map(([field, ref]) => {
      if (!table[field]) { dropped.push(field); return undefined; }
      // An unresolved variable reference must never become a literal in a
      // WHERE. `_resolveRef` returns the ref STRING when it names nothing,
      // so `where: {id: "applicationId"}` with no applicationId supplied
      // built `WHERE id = 'applicationId'` and RAN it — matching zero rows
      // on a text column (a silent no-op update reported as success) or
      // erroring deep in the driver on a typed one. Unlike a value, a
      // WHERE cannot be omitted: dropping it widens the statement to the
      // whole table. Refuse.
      if (typeof ref === "string" && _isUnresolvedRef(ref, ctx)) {
        throw new Error(
          `WHERE ${field} references process variable "${ref}", which was ` +
          `declared but never supplied — refusing to run with the variable ` +
          `name as a literal value`,
        );
      }
      const v = _resolveRef(ref, ctx);
      // An empty-string / null / undefined WHERE ref means the caller (a
      // trigger form or upstream node) didn't supply the id/lookup value.
      // Never let it reach Postgres — a typed column crashes with
      // "22P02 invalid input syntax for type uuid: ''", and an untyped
      // column would match every row.
      if (v === "" || v == null) {
        if (opts.strict) {
          throw new Error(
            `WHERE ${field} is empty — trigger form is missing an input for this workflow node`,
          );
        }
        emptyRefs.push(field);
        return undefined;
      }
      return eq(table[field], _coerceValue(v, table[field]));
    })
    .filter(Boolean) as any[];
  if (conds.length === 0) {
    // Config was provided but every entry filtered out (or {} was passed).
    // For destructive ops (db_update/db_delete) THIS IS DANGEROUS —
    // silently returning undefined would run UNFILTERED and wipe the whole
    // table. Fail loudly. For db_query (SELECT), an empty WHERE just means
    // "fetch all rows" — return undefined so the SELECT proceeds.
    if (opts.strict) {
      throw new Error(
        `WHERE resolved to zero conditions — ${entries.length === 0 ? "empty {} config" : `no config field matched the table (dropped: ${dropped.join(", ")}${emptyRefs.length ? `; empty-ref: ${emptyRefs.join(", ")}` : ""})`}`,
      );
    }
    if (dropped.length || emptyRefs.length) {
      console.warn(
        `[workflow] db_query: WHERE reduced to unfiltered SELECT — dropped=[${dropped.join(", ")}] emptyRefs=[${emptyRefs.join(", ")}]`,
      );
    }
    return undefined;
  }
  return conds.length === 1 ? conds[0] : and(...conds);
}

// Data-mutating handlers must never run unfiltered. Called by db_update /
// db_delete after _buildWhere: if no WHERE config was set at all, _buildWhere
// returns undefined by design (it's a pure resolver, not a policy layer) —
// this is where we refuse.
function _requireWhereOrThrow(action: "db_update" | "db_delete", config: any, where: any): void {
  if (where !== undefined) return;
  const hadConfig = config && typeof config.where === "object" && config.where !== null;
  throw new Error(
    hadConfig
      ? `[${action}] WHERE is empty — see _buildWhere error above`
      : `[${action}] refuses to run without a WHERE clause — set config.where on this node`,
  );
}

/**
 * A rules-engine FAILURE must never look like a rules engine that is absent.
 *
 * Both used to land in the same bare `catch`, so a bad regex or a malformed
 * rules/index.json silently disabled every validation and condition_action
 * rule for that write while the workflow reported success. Mirrors
 * `rethrowIfRulesEngineFailed` in data-engine.ts — the SAME defect existed on
 * three write paths (data-engine create, data-engine update, and here).
 */
function _rethrowIfRulesFailed(e: any, table: unknown, op: string): void {
  const missing =
    e?.code === "MODULE_NOT_FOUND" ||
    e?.code === "ERR_MODULE_NOT_FOUND" ||
    /Cannot find module|Failed to resolve/i.test(String(e?.message ?? ""));
  if (missing) return;
  console.error(
    `[workflow] rules engine FAILED for ${String(table)} ${op} — refusing to ` +
    `write without validation.`,
    e,
  );
  throw e;
}

export function registerDefaultActions(): void {
  // Register the execution-log writer once. Every node execution inside
  // engine.ts fires a row into `workflow_execution_log` for the panel's
  // History tab. Failures are swallowed at the source — never blocks the run.
  try {
    const { registerExecutionLogger } = require("./node-io");
    const wel: any = (schema as any).forgeWorkflowExecutionLog;
    if (wel && typeof registerExecutionLogger === "function") {
      registerExecutionLogger(async (row: any) => {
        await (db as any).insert(wel).values({
          runId: row.runId || "",
          workflowId: row.workflowId || "",
          nodeId: row.nodeId || "",
          nodeLabel: row.nodeLabel || "",
          actionType: row.actionType || "",
          stepIndex: row.stepIndex ?? 0,
          inputs: row.inputs ?? {},
          outputs: row.outputs ?? null,
          status: row.status || "completed",
          error: row.error ?? null,
          durationMs: row.durationMs ?? null,
        });
      });
    }
  } catch {
    // Schema not present (older generated app) — logging silently disabled.
  }

  // Real DB handlers — workflows actually read/write the database. `config`
  // carries { table, values: field→var, where: field→var } from the node.
  registerActionHandler("db_insert", async (config, ctx) => {
    const table = _resolveTable((config as any).table);
    if (!table) { console.warn("[workflow] db_insert: unknown table", (config as any).table); return { error: "unknown table" }; }
    try {
      const raw = _resolveValueMap((config as any).values, ctx, table);
      // Array-fanout: if ANY value resolved to an array of objects, treat that
      // as "insert one row per element" and merge the other (static) values
      // into each row. This is what LLM-authored workflows write when they
      // want to persist a list output from an earlier step — e.g. a Firecrawl
      // scrape returning [{price,currency,url}, …] against a rows table.
      // Without this each such node inserted ONE row with the array shoved
      // into a nonexistent `results` column, so every real column landed NULL.
      // Look for a value that IS an array, OR an envelope object whose
      // `.result` / `.data` / `.items` is an array. Firecrawl/other MCP
      // tools return {result:[...], raw:...} — the persist step points at
      // the whole envelope and we need to reach in one level to find rows.
      const findRowArray = (v: unknown): Array<Record<string, unknown>> | null => {
        if (Array.isArray(v) && v.length > 0 && typeof v[0] === "object" && v[0] !== null) {
          return v as Array<Record<string, unknown>>;
        }
        if (v && typeof v === "object") {
          for (const nk of ["result", "data", "items", "rows"]) {
            const inner = (v as Record<string, unknown>)[nk];
            if (Array.isArray(inner) && inner.length > 0 && typeof inner[0] === "object" && inner[0] !== null) {
              return inner as Array<Record<string, unknown>>;
            }
          }
        }
        return null;
      };
      let arrayEntry: [string, Array<Record<string, unknown>>] | null = null;
      for (const [k, v] of Object.entries(raw)) {
        const arr = findRowArray(v);
        if (arr) { arrayEntry = [k, arr]; break; }
      }
      if (arrayEntry) {
        const [arrKey, arr] = arrayEntry;
        const staticFields: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(raw)) {
          if (k !== arrKey) staticFields[k] = v;
        }
        const inserted: unknown[] = [];
        for (const item of arr) {
          const merged = { ...staticFields, ...(item as Record<string, unknown>) };
          const values = _finalizeInsert(table, merged, ctx);
          try {
            const rows = await (db as any).insert(table).values(values).returning();
            const row = Array.isArray(rows) ? rows[0] : rows;
            if (row) inserted.push(row);
          } catch (err) {
            console.warn(`[workflow] db_insert (row-fanout): row failed —`, err);
          }
        }
        const nid = (config as any).__nodeId;
        if (nid) ctx.variables[nid] = { rows: inserted, count: inserted.length };
        return { inserted: inserted.length };
      }
      // Business rules (condition→action): patch fields + reject. No-op unless a
      // rule targets this table. A show_error becomes { error } → the engine
      // fails the workflow → the form surfaces it. Rules-engine-absent is silent.
      try {
        const { evaluateRuleSetForTable } = await import("@/lib/rules");
        const rs = await evaluateRuleSetForTable(
          (config as any).table, "create", raw, (ctx as any).user,
        );
        if (rs.errors.length) return { error: rs.errors.join("; ") };
        Object.assign(raw, rs.patches);
      } catch (e: any) { _rethrowIfRulesFailed(e, (config as any).table, "write"); }
      const values = _finalizeInsert(table, raw, ctx);
      const rows = await (db as any).insert(table).values(values).returning();
      const row = Array.isArray(rows) ? rows[0] : rows;
      if (row && typeof row === "object") {
        // Legacy flat aliases (`scan_sessions_id`) — kept for
        // backward-compat with older plans.
        for (const [k, v] of Object.entries(row)) ctx.variables[`${(config as any).table}_${k}`] = v as unknown;
        // Node-scoped output — refs like `{{insert_scan_session.id}}`
        // dot-walk into this object via _resolveRef.
        const nid = (config as any).__nodeId;
        if (nid) ctx.variables[nid] = row;
      }
      return { inserted: row ?? true };
    } catch (err) {
      console.error("[workflow] db_insert failed:", err);
      reportFromError(err, {
        kind: "workflow",
        source_file: "src/lib/workflows/index.ts",
        workflow_id: (config as any)?.__workflowId || (ctx as any)?.workflow?.id,
        node_id: (config as any)?.__nodeId,
        page_route: typeof window !== "undefined" ? window.location?.pathname : undefined,
      });
      return { error: String(err) };
    }
  });

  registerActionHandler("db_update", async (config, ctx) => {
    const table = _resolveTable((config as any).table);
    if (!table) { console.warn("[workflow] db_update: unknown table", (config as any).table); return { error: "unknown table" }; }
    try {
      const raw = _resolveValueMap((config as any).values, ctx, table);
      try {
        const { evaluateRuleSetForTable } = await import("@/lib/rules");
        const rs = await evaluateRuleSetForTable(
          (config as any).table, "update", raw, (ctx as any).user,
        );
        if (rs.errors.length) return { error: rs.errors.join("; ") };
        Object.assign(raw, rs.patches);
      } catch (e: any) { _rethrowIfRulesFailed(e, (config as any).table, "write"); }
      const q = (db as any).update(table).set(raw);
      const where = _buildWhere(table, (config as any).where, ctx);
      _requireWhereOrThrow("db_update", config, where);
      const rows = await q.where(where).returning();
      const count = Array.isArray(rows) ? rows.length : 1;
      // `updated` (the legacy scalar) + contract-declared `updated: {count, rows}`.
      // Split naming — top-level `updated` used to be a plain number, so
      // {{node.output.updated.count}} bound to undefined. Return the shape
      // both existing and contract-authored mappings expect.
      // A0-1: the editor's contract (actionContracts.ts) advertises
      // `updated.count` and `updated.rows` as promotable outputs, but `updated`
      // was a NUMBER — so binding either one silently set no variable.
      // `updated` is now the object the contract describes; the flat aliases
      // stay so existing workflows that read {{n.output.count}} keep working.
      return {
        updated: { count, rows },
        updatedRows: rows,
        count,
        rows,
      };
    } catch (err) {
      console.error("[workflow] db_update failed:", err);
      reportFromError(err, {
        kind: "workflow",
        source_file: "src/lib/workflows/index.ts",
        workflow_id: (config as any)?.__workflowId || (ctx as any)?.workflow?.id,
        node_id: (config as any)?.__nodeId,
        page_route: typeof window !== "undefined" ? window.location?.pathname : undefined,
      });
      return { error: String(err) };
    }
  });

  registerActionHandler("db_delete", async (config, ctx) => {
    const table = _resolveTable((config as any).table);
    if (!table) return { error: "unknown table" };
    try {
      const q = (db as any).delete(table);
      const where = _buildWhere(table, (config as any).where, ctx);
      _requireWhereOrThrow("db_delete", config, where);
      // Drizzle-orm's DELETE ... RETURNING lets us honor the contract-
      // declared `deleted.count` output. Fall back to the boolean if the
      // driver doesn't support returning().
      let count = 0;
      try {
        const rows: any = await (q.where(where) as any).returning();
        count = Array.isArray(rows) ? rows.length : 0;
      } catch {
        await q.where(where);
      }
      // A0-2: the contract advertises `deleted.count`, but `deleted` was a
      // BOOLEAN. The count was already computed — it just was not reachable
      // where the editor said it would be.
      return { deleted: { count }, count };
    } catch (err) {
      console.error("[workflow] db_delete failed:", err);
      reportFromError(err, {
        kind: "workflow",
        source_file: "src/lib/workflows/index.ts",
        workflow_id: (config as any)?.__workflowId || (ctx as any)?.workflow?.id,
        node_id: (config as any)?.__nodeId,
        page_route: typeof window !== "undefined" ? window.location?.pathname : undefined,
      });
      return { error: String(err) };
    }
  });

  registerActionHandler("db_query", async (config, ctx) => {
    const table = _resolveTable((config as any).table);
    if (!table) return { rows: [] };
    try {
      const q = (db as any).select().from(table);
      // db_query is a SELECT — empty WHERE is a legitimate "fetch all
      // rows" pattern, not a config error. Pass strict:false so
      // _buildWhere degrades gracefully instead of throwing. Destructive
      // ops (db_update/db_delete) below still use strict:true, gated by
      // _requireWhereOrThrow, so unfiltered writes remain impossible.
      const where = _buildWhere(table, (config as any).where, ctx, { strict: false });
      const rows = await (where ? q.where(where) : q);
      // Contract declared `count` alongside `rows` — provide both.
      return { rows, count: Array.isArray(rows) ? rows.length : 0 };
    } catch (err) { console.error("[workflow] db_query failed:", err); return { error: String(err), rows: [], count: 0 }; }
  });

  // Call an MCP server tool (Firecrawl, Bright Data, Apify, custom …).
  // Config carries:
  //   mcp_server_id:   the hex12 slug env_writer wrote (MCP_SERVER_<slug>_URL)
  //     — OR —
  //   mcp_server_name: human name; runtime resolves to slug via MCP_SERVER_<slug>_NAME
  //   mcp_tool_name:   the tool advertised by the server (firecrawl_search, etc.)
  //   args:            record of args to forward to the tool. Values may be
  //                    {{node.field}} refs which _resolveValueMap expands.
  registerActionHandler("mcp_tool_call", async (config, ctx) => {
    const cfg = config as any;
    let serverId: string | undefined = cfg.mcp_server_id;
    if (!serverId && cfg.mcp_server_name) {
      // Iterate env for a NAME match. env_writer emits MCP_SERVER_<slug>_NAME
      // when the platform config carries a human name; if not present we
      // fall through to error so the author sees the config gap.
      const target = String(cfg.mcp_server_name).toLowerCase();
      for (const [k, v] of Object.entries(process.env)) {
        if (k.startsWith("MCP_SERVER_") && k.endsWith("_NAME") &&
            String(v ?? "").toLowerCase() === target) {
          serverId = k.slice("MCP_SERVER_".length, -"_NAME".length);
          break;
        }
      }
    }
    if (!serverId) {
      const msg = `mcp_tool_call: no server matched (id=${cfg.mcp_server_id ?? ""} name=${cfg.mcp_server_name ?? ""})`;
      console.warn(`[workflow] ${msg}`);
      return { error: msg, result: null };
    }
    const toolName = String(cfg.mcp_tool_name || "").trim();
    if (!toolName) {
      return { error: "mcp_tool_call: mcp_tool_name is required", result: null };
    }
    const args = cfg.args && typeof cfg.args === "object"
      ? _resolveValueMap(cfg.args, ctx) : {};
    try {
      const { callMcpTool } = await import("@/lib/integrations/mcpClientPool");
      const result = await callMcpTool(serverId, toolName, args);
      // Unwrap text blocks so downstream nodes see a plain string/object.
      // Keep raw envelope on `.raw` for advanced binding.
      const textBlocks = Array.isArray(result?.content)
        ? result.content.filter((b: any) => b?.type === "text")
                        .map((b: any) => b.text)
                        .join("\n") : "";
      let parsed: unknown = null;
      if (textBlocks) {
        try { parsed = JSON.parse(textBlocks); } catch { parsed = textBlocks; }
      }
      return {
        result: parsed,
        text: textBlocks,
        isError: !!result?.isError,
        raw: result,
      };
    } catch (err) {
      console.error("[workflow] mcp_tool_call failed:", err);
      return { error: String(err), result: null };
    }
  });

  registerActionHandler("http_call", async (config, ctx) => {
    if (!config.url) return null;
    try {
      // Resolve template refs inside url/body/headers. Without this a workflow
      // author writing `body: {file_url: "{{fileUrl}}"}` shipped the literal
      // moustache string to the endpoint (the sidecar 500'd on a non-URL).
      // One-level deep walk: strings go through _resolveRef, objects/arrays
      // recurse.
      const resolveDeep = (v: unknown): unknown => {
        if (typeof v === "string") return _resolveRef(v, ctx);
        if (Array.isArray(v)) return v.map(resolveDeep);
        if (v && typeof v === "object") {
          const out: Record<string, unknown> = {};
          for (const [k, vv] of Object.entries(v as Record<string, unknown>)) out[k] = resolveDeep(vv);
          return out;
        }
        return v;
      };
      const resolvedUrl = resolveDeep(config.url) as string;
      const resolvedBody = config.body ? resolveDeep(config.body) : undefined;
      // Merge author-supplied headers with the JSON default so the
      // `headers` config surface stops being a placebo field
      // (workflow-audit contract-alignment #9).
      const authorHeaders =
        (config as any).headers && typeof (config as any).headers === "object"
          ? (resolveDeep((config as any).headers) as Record<string, string>)
          : {};
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...authorHeaders,
      };
      // 30 s ceiling — a hung endpoint used to hang the whole workflow run
      // indefinitely. AbortSignal.timeout is a Node 18+/browser built-in.
      const controller = new AbortController();
      const timeoutMs = Number((config as any).timeoutMs ?? 30_000) || 30_000;
      const timeout = setTimeout(() => controller.abort(), timeoutMs);
      const res = await fetch(String(resolvedUrl), {
        method: String(config.method || "GET"),
        headers,
        body: resolvedBody !== undefined ? JSON.stringify(resolvedBody) : undefined,
        signal: controller.signal,
      });
      clearTimeout(timeout);
      // Response headers as a plain object so the contract-declared
      // `headers` output can be promoted. Body is best-effort JSON; falls
      // back to text so a non-JSON response doesn't crash the node.
      const respHeaders: Record<string, string> = {};
      res.headers.forEach((v, k) => { respHeaders[k] = v; });
      let body: unknown;
      const contentType = res.headers.get("content-type") || "";
      body = contentType.includes("application/json")
        ? await res.json().catch(() => null)
        : await res.text().catch(() => null);
      return {
        status: res.status,
        ok: res.ok,
        body,
        headers: respHeaders,
        // Legacy top-level echo of the JSON body so pre-fix workflows that
        // bound {{node.output.someField}} still resolve.
        ...(body && typeof body === "object" && !Array.isArray(body) ? body : {}),
      };
    } catch (err) { console.warn("[workflow] http_call failed:", err); return { error: String(err) }; }
  });

  // Real notification — persists an in-app notification row (queryable via
  // /api/notifications, displayable with ActivityFeed/Banner/List). Config keys
  // (all support {{var}} refs): title|subject, message|body, to|userId, toRole|
  // assigneeRole, type, entityId.
  registerActionHandler("send_notification", async (config, ctx) => {
    const title = String(_resolveRef((config as any).title ?? (config as any).subject ?? "Notification", ctx) ?? "Notification");
    const message = String(_resolveRef((config as any).message ?? (config as any).body ?? "", ctx) ?? "");
    const userId = _resolveRef((config as any).to ?? (config as any).userId ?? null, ctx);
    const role = (config as any).toRole ?? (config as any).assigneeRole ?? null;
    const type = String((config as any).notificationType ?? (config as any).type ?? "info");
    const entityId = _resolveRef((config as any).entityId ?? null, ctx);
    const table = (schema as any).forgeNotifications;
    let notificationId: string | null = null;
    if (table) {
      try {
        const inserted: any = await (db as any).insert(table).values({
          title, message, userId: userId ? String(userId) : null,
          role: role ? String(role) : null, type, entityId: entityId ? String(entityId) : null, read: false,
        }).returning();
        const row = Array.isArray(inserted) ? inserted[0] : inserted;
        notificationId = row?.id ?? null;
      } catch (e) { console.warn("[workflow] send_notification persist failed:", e); }
    }
    // Contract-declared `notificationId` — was always null before.
    return { sent: true, channel: "in_app", notificationId };
  });

  // Real email — provider priority (mutually exclusive):
  //   1. SMTP (via nodemailer) when SMTP_HOST is set — corporate mail servers,
  //      Gmail/Outlook app passwords, self-hosted (Postfix, Mailu, …).
  //   2. Resend (HTTP, no npm dep) when RESEND_API_KEY is set — hosted email API.
  //   3. In-app notification fallback so the message is never lost.
  // Credentials resolved via getSecret() so admins can override env from the
  // /settings/integrations UI without restarting the app.
  registerActionHandler("send_email", async (config, ctx) => {
    let to = String(_resolveRef((config as any).to ?? (config as any).email ?? "", ctx) ?? "");
    const subject = String(_resolveRef((config as any).subject ?? (config as any).title ?? "", ctx) ?? "");
    const body = String(_resolveRef((config as any).body ?? (config as any).message ?? (config as any).html ?? "", ctx) ?? "");
    // When the generator only supplied `recipientRole` (the common case for
    // planner-emitted "email the admin when X" workflows), the config carries
    // no `to` and every provider path used to fall through to the in-app
    // notification while still returning `{sent:true, channel:"email"}` — a
    // silent lie. Resolve role → user.email once here (same pattern as
    // _resolveAssignee) so genuine email sends work; still fall through to
    // the in-app persist if no matching user exists, but surface it in the
    // return value so downstream nodes/audits can see nothing was actually
    // emailed.
    if (!to) {
      const roleRef = (config as any).recipientRole ?? (config as any).toRole ?? (config as any).assigneeRole;
      const role = roleRef ? String(_resolveRef(roleRef, ctx) ?? "") : "";
      if (role) {
        try {
          const { sql } = await import("drizzle-orm");
          const res: any = await (db as any).execute(
            sql`SELECT email FROM users WHERE role = ${role} AND email IS NOT NULL LIMIT 1`,
          );
          const rows = Array.isArray(res) ? res : (res?.rows ?? []);
          const email = rows[0]?.email;
          if (email) to = String(email);
        } catch {
          // users table absent or no role/email column — fall through to
          // the in-app persist with a warning in the return value.
        }
      }
    }
    const { getSecret } = await import("@/lib/integrations/resolver");
    const from = (await getSecret("resend", "FORGE_EMAIL_FROM")) || "notifications@example.com";

    // 1. SMTP wins when SMTP_HOST is set.
    const smtpHost = await getSecret("smtp", "SMTP_HOST");
    if (smtpHost && to) {
      const port = Number((await getSecret("smtp", "SMTP_PORT")) || "587");
      const user = await getSecret("smtp", "SMTP_USER");
      const pass = await getSecret("smtp", "SMTP_PASSWORD");
      try {
        // Lazy import so a missing nodemailer install falls through to Resend
        // rather than breaking the build.
        const nm: any = await import(/* webpackIgnore: true */ "nodemailer");
        const transporter = nm.createTransport({
          host: smtpHost,
          port,
          secure: port === 465, // 465 = SSL, 587/25 = STARTTLS (nodemailer negotiates)
          auth: user && pass ? { user, pass } : undefined,
        });
        const info: any = await transporter.sendMail({ from, to, subject, html: `<p>${body}</p>` });
        // Contract-declared `messageId`. nodemailer surfaces it as info.messageId.
        return { sent: true, channel: "smtp", messageId: info?.messageId ?? null };
      } catch (e) {
        console.warn("[workflow] send_email: smtp failed:", e);
        // Fall through to the fallback — do NOT try Resend after SMTP was
        // configured; the two are mutually exclusive.
      }
    } else {
      // 2. Resend — only when SMTP isn't configured.
      const key = await getSecret("resend", "RESEND_API_KEY");
      if (key && to) {
        try {
          const res = await fetch("https://api.resend.com/emails", {
            method: "POST",
            headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
            body: JSON.stringify({ from, to, subject, html: `<p>${body}</p>` }),
          });
          if (res.ok) {
            const j: any = await res.json().catch(() => null);
            return { sent: true, channel: "email", messageId: j?.id ?? null };
          }
          console.warn("[workflow] send_email: resend error", res.status);
        } catch (e) { console.warn("[workflow] send_email failed:", e); }
      }
    }

    // 3. Fallback — persist so the message is never lost. But be honest
    // about it: return channel="in_app" AND a warning flag so a downstream
    // audit/UI can distinguish "actually delivered by email" from "landed
    // as an in-app notification because no address was resolvable / the
    // provider errored". The `sent:true` claim used to hide both failure
    // modes silently.
    const table = (schema as any).forgeNotifications;
    if (table) {
      try {
        await (db as any).insert(table).values({ title: subject || "Email", message: body, userId: null, role: null, type: "email", entityId: null, read: false });
      } catch { /* ignore */ }
    }
    return {
      sent: true,
      channel: "in_app",
      // A0-7: `messageId` is contract-declared, but only the two PROVIDER paths
      // returned it — so on this fallback the declared path resolved to
      // undefined with no explanation. Returning an explicit null keeps the
      // path resolvable and says what it means: delivered, but not by a
      // provider that issues message ids. `channel` and `warning` carry the
      // detail.
      messageId: null,
      warning: to
        ? "email provider failed — persisted as in-app notification"
        : "no email address resolvable (no `to`, and role→email lookup empty) — persisted as in-app notification",
    };
  });

  // custom — a design-time compute step. Evaluates config.expression (or code)
  // through the sandboxed FEEL-lite engine (safe: expressions only, no host
  // access) against the process variables, and stores the result in config.assignTo
  // when given. Empty / comment-only code returns { ran: false } but never crashes.
  registerActionHandler("custom", async (config, ctx) => {
    const c = config as Record<string, unknown>;
    const expr = (c.expression ?? c.code ?? c.script) as string | undefined;
    if (typeof expr !== "string" || !expr.trim() || expr.trim().startsWith("//")) {
      return { ran: false };
    }
    try {
      const result = evaluateExpression(expr, (ctx.variables ?? {}) as Record<string, unknown>);
      const target = (c.assignTo ?? c.outputVar) as string | undefined;
      if (target) ctx.variables[target] = result;
      // A0-3: the contract advertises an output named `value`; this returned
      // only `{ran, result}`. Both names are returned so neither the contract
      // nor any existing {{n.output.result}} reference breaks.
      return { ran: true, result, value: result };
    } catch (err) {
      console.warn("[workflow] custom expression failed:", err);
      return { ran: false, error: String(err) };
    }
  });

  // Generate a PDF (invoice / certificate / report) and store it. Config:
  // title, subtitle?, footer?, fields?: [{label, value(ref)}] OR record (a var
  // resolving to an object → its entries become fields), table?: {columns, rows}.
  // Returns { url, fileId } so a downstream step can save it or notify.
  registerActionHandler("generate_document", async (config, ctx) => {
    try {
      const c = config as Record<string, any>;
      const spec: any = {
        title: String(_resolveRef(c.title ?? "Document", ctx) ?? "Document"),
        subtitle: c.subtitle ? String(_resolveRef(c.subtitle, ctx)) : undefined,
        footer: c.footer ? String(_resolveRef(c.footer, ctx)) : undefined,
      };
      if (Array.isArray(c.fields)) {
        spec.fields = c.fields.map((f: any) => ({ label: f.label, value: _resolveRef(f.value, ctx) }));
      } else {
        const rec = _resolveRef(c.record ?? "{{input}}", ctx);
        if (rec && typeof rec === "object" && !Array.isArray(rec)) {
          spec.fields = Object.entries(rec as Record<string, unknown>).map(([k, v]) => ({ label: k, value: v }));
        }
      }
      if (c.table && Array.isArray(c.table.columns)) spec.table = c.table;

      const { buildPdf } = await import("@/lib/pdf");
      const bytes = await buildPdf(spec);
      const { saveFile } = await import("@/lib/storage");
      const saved = await saveFile({
        buffer: Buffer.from(bytes),
        filename: `${spec.title}.pdf`,
        contentType: "application/pdf",
        uploadedById: null,
      });
      return { generated: true, url: saved.url, fileId: saved.id };
    } catch (err) {
      console.warn("[workflow] generate_document failed:", err);
      return { generated: false, error: String(err) };
    }
  });

  // R3: emit_event — writes a durable forge_events row and kicks inline
  // processing (which starts event-triggered workflows + resumes
  // wait_for_event pauses). Payload values support {{refs}} exactly like
  // db_insert values. Non-fatal: a bus failure returns a warning, never
  // an {error} the engine would escalate.
  // NOTE: the string literal stays adjacent to registerActionHandler( —
  // services/workflow_node_contracts.py parses registrations with a regex.
  registerActionHandler("emit_event", makeEmitEventHandler({
    emit: async (type, opts) => {
      const { emitEventAndProcess } = await import("../events/bus");
      return emitEventAndProcess(type, opts);
    },
    resolveRef: (ref, ctx) => _resolveRef(ref, ctx as WorkflowExecutionContext),
    resolveMap: (map, ctx) => _resolveMap(map, ctx as WorkflowExecutionContext),
  }));

  // R3: wait_for_event is intercepted by engine.ts BEFORE handler
  // dispatch (it pauses the run through the human-task mechanism). This
  // registration exists only so the strict unknown-actionType guard never
  // fires if a custom caller dispatches the config directly.
  registerActionHandler("wait_for_event", async (config) => ({
    waiting: true,
    event: (config as { event?: unknown }).event ?? null,
  }));

  // Real AI handlers (Claude-backed, mock fallback when no ANTHROPIC_API_KEY).
  // ai_generate / ai_classify / ai_extract / ai_decide — see ./ai.ts.
  registerAIActions();

  // PaddleOCR sidecar handler — ocr_document. First-class OCR primitive for
  // banking / healthcare / doc-intelligence apps. See ./ocr.ts.
  registerOcrActions();
}
