/**
 * Per-node input/output contract runtime — the counterpart to the
 * `actionContracts.ts` catalog in the platform editor.
 *
 *   config.inputMappings[]  → resolved values dropped onto config so
 *                             handlers keep seeing the flat legacy shape
 *   config.outputMappings[] → after the handler returns, selected
 *                             outputs are promoted to named process vars
 *
 * The write to `workflow_execution_log` also lives here so engine.ts
 * doesn't grow a DB dependency.
 *
 * Spec: docs/superpowers/specs/2026-07-22-workflow-node-contracts.md
 */

import { evaluateExpression } from "../feel-lite";

export type MappingSource = "variable" | "literal" | "expression";

export interface InputMapping {
  name: string;
  source: MappingSource;
  value: unknown;
}

export interface OutputMapping {
  output: string;
  processVar: string;
}

// ── Input resolution ─────────────────────────────────────────────────

/**
 * Walk a dotted path against ctx.variables. Understands the two shapes
 * downstream nodes emit: `<nodeId>.output.<field>` and the legacy
 * `trigger.<field>`.
 */
function readPath(source: any, path: string): unknown {
  const parts = path.split(".");
  let cur: any = source;
  for (const p of parts) {
    if (cur === null || cur === undefined) return undefined;
    cur = cur[p];
  }
  return cur;
}

function resolveOne(
  mapping: InputMapping,
  variables: Record<string, unknown>,
): unknown {
  if (mapping.source === "literal") {
    // Literals authored through the KeyValueMapper can contain nested
    // `{{path}}` references — e.g. { candidateProfileId: "{{candidateProfileId}}" }.
    // Walk the value and interpolate any string that looks like a ref.
    return walkAndInterpolate(mapping.value, variables);
  }
  if (mapping.source === "variable") {
    if (typeof mapping.value !== "string") return mapping.value;
    return readPath(variables, mapping.value);
  }
  if (mapping.source === "expression") {
    if (typeof mapping.value !== "string") return mapping.value;
    try {
      return evaluateExpression(mapping.value, variables);
    } catch {
      return undefined;
    }
  }
  return undefined;
}

const REF_RE = /^\s*\{\{\s*(.+?)\s*\}\}\s*$/;

/**
 * Recursively replace `"{{path}}"` strings inside objects/arrays with
 * the value at `path` in `variables`. Leaves everything else alone.
 * Handles the shape the KeyValueMapper emits without extra ceremony.
 */
function walkAndInterpolate(value: unknown, variables: Record<string, unknown>): unknown {
  if (typeof value === "string") {
    const m = value.match(REF_RE);
    return m ? readPath(variables, m[1]) : value;
  }
  if (Array.isArray(value)) {
    return value.map((v) => walkAndInterpolate(v, variables));
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = walkAndInterpolate(v, variables);
    }
    return out;
  }
  return value;
}

/**
 * Fold every `inputMappings[]` entry into a shallow object with dotted
 * keys expanded into nested objects. Given
 *   [ { name: "table", source: "literal", value: "users" },
 *     { name: "values.email", source: "variable", value: "trigger.email" } ]
 * and variables { trigger: { email: "a@b.com" } }, this returns
 *   { table: "users", values: { email: "a@b.com" } }
 * which the handler consumes as its config.
 */
export function resolveInputMappings(
  mappings: InputMapping[] | undefined,
  variables: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!Array.isArray(mappings) || mappings.length === 0) return out;
  for (const m of mappings) {
    if (!m || typeof m.name !== "string") continue;
    const resolved = resolveOne(m, variables);
    const parts = m.name.split(".");
    if (parts.length === 1) {
      out[m.name] = resolved;
      continue;
    }
    // Nested key: values.email → out.values.email
    let cur: Record<string, unknown> = out;
    for (let i = 0; i < parts.length - 1; i++) {
      const key = parts[i];
      if (typeof cur[key] !== "object" || cur[key] === null) {
        cur[key] = {};
      }
      cur = cur[key] as Record<string, unknown>;
    }
    cur[parts[parts.length - 1]] = resolved;
  }
  return out;
}

// ── Output promotion ─────────────────────────────────────────────────

/**
 * For each declared outputMapping, look the value up on the handler
 * result and set it under the named process variable. Missing keys are
 * left absent (the raw path `<nodeId>.output.<field>` still works).
 */
export function applyOutputMappings(
  mappings: OutputMapping[] | undefined,
  handlerResult: unknown,
  variables: Record<string, unknown>,
): void {
  if (!Array.isArray(mappings) || mappings.length === 0) return;
  for (const m of mappings) {
    if (!m || !m.processVar) continue;
    const value = readPath(handlerResult, m.output);
    if (value !== undefined) variables[m.processVar] = value;
  }
}

// ── Execution log ────────────────────────────────────────────────────

export interface ExecutionLogRow {
  runId: string;
  workflowId: string;
  nodeId: string;
  nodeLabel: string;
  actionType: string;
  stepIndex: number;
  inputs: Record<string, unknown>;
  outputs: unknown;
  status: "completed" | "failed" | "skipped" | "running";
  error?: string;
  durationMs?: number;
}

let logWriter: ((row: ExecutionLogRow) => Promise<void> | void) | null = null;

/**
 * Register the DB-writer for execution-log rows. Called once at
 * runtime bootstrap (workflows/index.ts) with a function that inserts
 * into `workflow_execution_log`. Kept out of engine.ts so this file
 * has no drizzle/DB import — the engine template stays framework-neutral.
 */
export function registerExecutionLogger(
  writer: (row: ExecutionLogRow) => Promise<void> | void,
): void {
  logWriter = writer;
}

/**
 * Fire-and-forget. If registration hasn't happened (e.g. offline test
 * harness) or the write errors, the workflow continues — the log is
 * observability, not correctness.
 */
export async function writeExecutionLog(row: ExecutionLogRow): Promise<void> {
  if (!logWriter) return;
  try {
    await logWriter(row);
  } catch {
    // Swallow — never let observability break the run.
  }
}
