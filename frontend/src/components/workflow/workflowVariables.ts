import type { AppModel } from "@/types/app-model";
import { asObjectList } from "./config-guards";
import type {
  ProcessVariable,
  WorkflowNodeConfig,
  WorkflowNodeSerialized,
} from "@/types/workflow";
import { getContract, type ParamType } from "./actionContracts";

export type VariableGroup =
  | "process-variable"    // opt-in named var promoted from a node's output
  | "trigger"             // trigger.<field>
  | "node-output"         // <upstreamNodeId>.output.<field>
  | "system";

export interface WorkflowVariable {
  /** Fully-qualified path, no braces. e.g. "trigger.email", "create_user.output.inserted.id" */
  path: string;
  type: ParamType | "unknown";
  group: VariableGroup;
  /** Where it comes from — shown in the picker as the group heading. */
  sourceLabel: string;
}

/**
 * Enumerate every variable a node at `currentNodeId` can legally read.
 * Ordered: named process vars first (nicest handles) → trigger fields
 * → upstream node outputs → system fields.
 *
 * Node outputs come from the ACTION_CONTRACTS declaration, so downstream
 * nodes discover them without the user typing anything.
 */
export function collectWorkflowVariables(args: {
  processVariables?: ProcessVariable[];
  appModel?: AppModel | null;
  nodes: WorkflowNodeSerialized[];
  /**
   * A2-2: without edges, "upstream" can only be guessed from array position.
   * Optional so existing callers keep working — they fall back to the old
   * positional behaviour rather than breaking — but any caller that has the
   * graph should pass it.
   */
  edges?: Array<{ source: string; target: string }>;
  currentNodeId: string;
}): WorkflowVariable[] {
  const { processVariables, appModel, nodes, edges, currentNodeId } = args;
  const out: WorkflowVariable[] = [];

  // 1. Named process variables — the clean handles.
  for (const pv of processVariables ?? []) {
    if (!pv.name) continue;
    out.push({
      path: pv.name,
      type: pv.type as ParamType,
      group: "process-variable",
      sourceLabel: "Process variables",
    });
  }

  // 2. Trigger fields — every column of every entity is potentially
  //    on the trigger payload for db_change / manual submit triggers.
  //    Users often use them as "trigger.<field>".
  if (appModel?.database?.tables) {
    for (const t of appModel.database.tables) {
      for (const c of t.columns) {
        out.push({
          path: `trigger.${c.name}`,
          type: "string",
          group: "trigger",
          sourceLabel: `Trigger · ${t.name}`,
        });
      }
    }
  }

  // 3. Upstream node outputs — from the declared contract of every
  //    node that comes before the current one. Even if the author
  //    hasn't promoted them, they're always reachable.
  const upstreamIds = collectAncestors(edges, currentNodeId);

  for (const n of nodes) {
    // A2-2: this was `if (n.id === currentNodeId) break;` — "upstream" decided
    // by ARRAY POSITION. LLM- and layout-produced node arrays are not
    // topologically sorted, so a genuinely upstream node listed later was
    // hidden from the picker while an unreachable one could be offered.
    // With edges we walk the graph; without them we keep the old behaviour so
    // no caller regresses.
    if (upstreamIds) {
      if (!upstreamIds.has(n.id)) continue;
    } else if (n.id === currentNodeId) {
      break;
    }
    // A2-3: `.config` was guarded but `.data` was not. normalizeWorkflowNodes
    // deliberately passes unrecognised nodes through unchanged, so a node with
    // no `data` reaches here and threw — taking down the whole panel.
    const contract = getContract(n?.data?.config?.actionType);
    if (contract) {
      for (const o of contract.outputs) {
        out.push({
          path: `${n.id}.output.${o.name}`,
          type: o.type,
          group: "node-output",
          sourceLabel: `${n?.data?.label || n.id}`,
        });
      }
    }
    // Also expose promoted named vars from output mappings.
    // A2-3 + A4-3: `.data` was unguarded, and a non-array or null-entry
    // outputMappings threw here too — this list is read on every render.
    for (const m of asObjectList<{ processVar?: string }>(n?.data?.config?.outputMappings)) {
      if (m.processVar) {
        out.push({
          path: m.processVar,
          type: "unknown",
          group: "process-variable",
          sourceLabel: "Process variables",
        });
      }
    }
    // Permissive fallbacks so legacy references keep working.
    out.push({
      path: `${n.id}.output`,
      type: "object",
      group: "node-output",
      sourceLabel: `${n?.data?.label || n.id}`,
    });
    out.push({
      path: `${n.id}.result`,
      type: "object",
      group: "node-output",
      sourceLabel: `${n?.data?.label || n.id}`,
    });
  }

  // 4. System fields.
  out.push(
    { path: "trigger.requesterId", type: "uuid", group: "system", sourceLabel: "System" },
    { path: "trigger.timestamp", type: "date", group: "system", sourceLabel: "System" },
  );

  // Dedupe by path (named vars can shadow trigger fields, that's fine —
  // first one wins).
  const seen = new Set<string>();
  return out.filter((v) => {
    if (seen.has(v.path)) return false;
    seen.add(v.path);
    return true;
  });
}

/**
 * Read a value out of the legacy flat-config shape when the new
 * `inputMappings` array doesn't yet contain an entry for this input.
 * This keeps existing workflows rendering correctly without a migration
 * step and lets the panel silently upgrade on next save.
 */
export function readLegacyInputValue(
  config: WorkflowNodeConfig,
  inputName: string,
): unknown {
  // Direct top-level: "table", "to", "subject", …
  if (inputName in (config as Record<string, unknown>)) {
    return (config as Record<string, unknown>)[inputName];
  }
  // Dotted "values.email" → config.values?.email  etc.
  const [head, ...rest] = inputName.split(".");
  if (rest.length && head in (config as Record<string, unknown>)) {
    let cur: unknown = (config as Record<string, unknown>)[head];
    for (const seg of rest) {
      if (cur && typeof cur === "object" && seg in (cur as Record<string, unknown>)) {
        cur = (cur as Record<string, unknown>)[seg];
      } else {
        return undefined;
      }
    }
    return cur;
  }
  return undefined;
}

/**
 * Every node that can actually run BEFORE `currentNodeId`, by walking edges
 * backwards. Returns null when there are no edges to walk, so the caller can
 * fall back rather than silently offering nothing.
 *
 * Cycle-safe: `seen` guards the queue, so a loop in the graph terminates
 * instead of hanging the panel.
 */
function collectAncestors(
  edges: Array<{ source: string; target: string }> | undefined,
  currentNodeId: string,
): Set<string> | null {
  if (!Array.isArray(edges) || edges.length === 0) return null;

  const incoming = new Map<string, string[]>();
  for (const e of edges) {
    if (!e || typeof e.source !== "string" || typeof e.target !== "string") continue;
    const list = incoming.get(e.target);
    if (list) list.push(e.source);
    else incoming.set(e.target, [e.source]);
  }

  const seen = new Set<string>();
  const queue = [...(incoming.get(currentNodeId) ?? [])];
  while (queue.length) {
    const id = queue.pop()!;
    if (id === currentNodeId || seen.has(id)) continue;   // never offer self
    seen.add(id);
    for (const parent of incoming.get(id) ?? []) queue.push(parent);
  }
  return seen;
}
