/**
 * Dry-run a workflow against the payload a control sends — the real engine's
 * resolution, none of its effects.
 *
 * "Verified" used to stop at the Blueprint: a control names a workflow, the
 * workflow declares its inputs, the row is in scope. Then the row action
 * posted `{ id }`, the step read `{{record.id}}`, and the first click met
 * "WHERE id is empty". Nothing between the document and a person's click ran
 * the code that ships.
 *
 * This does, at build time: for every db step it resolves the WHERE and the
 * values exactly as `db_update`/`db_delete`/`db_insert` would — same
 * `_buildWhere` (strict), same Drizzle columns, same `_resolveRef` — with the
 * payload from `src/contracts/dispatches.json`, and reports what would have
 * refused. No statement is executed; `@/db` is imported but never queried.
 *
 * Earlier steps' outputs are unknowable without running them, so every other
 * node key is seeded with a value that answers any path — a reference into
 * a previous step is "supplied by the run", never "empty". What remains
 * empty is what the control did not send.
 */
import {
  _buildWhere, _resolveTable, _resolveValueMap, listWorkflows,
} from "./index";
import type { WorkflowDefinition, WorkflowExecutionContext } from "./types";
import { STEP_OUTPUT } from "./dry-run-stand-in";

export interface DryRunProblem {
  node: string;
  actionType: string;
  problem: string;
}

export interface DryRunResult {
  workflow: string;
  ok: boolean;
  checked: number;
  problems: DryRunProblem[];
}

// Any depth answers — see dry-run-stand-in.ts for why one level was not enough.
const _STEP_OUTPUT: unknown = STEP_OUTPUT;

function _actionNodes(def: WorkflowDefinition): Array<{ id: string; config: any }> {
  const nodes: any[] = ((def as any).definition?.nodes ?? (def as any).nodes ?? []) as any[];
  return nodes
    .map((n) => ({ id: String(n.id ?? n.key ?? "?"), config: n?.data?.config ?? n?.config ?? {} }))
    .filter((n) => typeof n.config?.actionType === "string" && n.config.actionType.startsWith("db_"));
}

function _allNodeIds(def: WorkflowDefinition): string[] {
  const nodes: any[] = ((def as any).definition?.nodes ?? (def as any).nodes ?? []) as any[];
  return nodes.map((n) => String(n.id ?? n.key ?? "")).filter(Boolean);
}

/** Resolve one workflow's db steps against `input`, reporting what would refuse. */
export function dryRunWorkflow(
  def: WorkflowDefinition,
  input: Record<string, unknown>,
  user: WorkflowExecutionContext["user"] = { id: "dry-run", role: "admin", email: "dry-run@example.com" } as any,
): DryRunResult {
  const problems: DryRunProblem[] = [];
  const variables: Record<string, unknown> = { ...input, user: { ...(user as any) } };
  for (const id of _allNodeIds(def)) if (!(id in variables)) variables[id] = _STEP_OUTPUT;
  const ctx = { input, variables, log: [], user } as unknown as WorkflowExecutionContext;
  const steps = _actionNodes(def);
  for (const { id, config } of steps) {
    const actionType = String(config.actionType);
    const table = _resolveTable(config.table);
    if (!table) {
      problems.push({ node: id, actionType, problem: `table ${JSON.stringify(config.table)} is not in the schema` });
      continue;
    }
    if (actionType === "db_update" || actionType === "db_delete") {
      try {
        const where = _buildWhere(table, config.where, ctx, { strict: true });
        if (where === undefined) {
          problems.push({ node: id, actionType, problem: "WHERE resolved to nothing — the step would refuse to run" });
        }
      } catch (e) {
        problems.push({ node: id, actionType, problem: String((e as Error)?.message ?? e) });
      }
    }
    if (actionType === "db_insert" || actionType === "db_update") {
      try {
        const values = _resolveValueMap(config.values, ctx, table);
        const unknown = Object.keys(config.values ?? {}).filter((k) => !(table as any)[k]);
        if (unknown.length) {
          problems.push({ node: id, actionType, problem: `values name columns the table does not have: ${unknown.join(", ")}` });
        }
        const empty = Object.entries(config.values ?? {})
          .filter(([k, ref]) => typeof ref === "string" && /\{\{/.test(ref) && (values[k] === "" || values[k] == null))
          .map(([k, ref]) => `${k} (${ref})`);
        if (empty.length) {
          problems.push({ node: id, actionType, problem: `values resolve to nothing from this control's payload: ${empty.join(", ")}` });
        }
      } catch (e) {
        problems.push({ node: id, actionType, problem: String((e as Error)?.message ?? e) });
      }
    }
  }
  return { workflow: String((def as any).blueprintId ?? def.id), ok: problems.length === 0, checked: steps.length, problems };
}

/** Find a loaded definition by Blueprint id (`FLOW-003`) or slug (`delete-record`). */
export async function findWorkflow(idOrSlug: string): Promise<WorkflowDefinition | undefined> {
  const all = await listWorkflows();
  return all.find((w) => (w as any).blueprintId === idOrSlug || w.id === idOrSlug || (w as any).name === idOrSlug);
}
