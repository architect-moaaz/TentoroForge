import type { NodeLogDTO, NodeVisualStatus } from "./types";

function mapLogStatus(s: NodeLogDTO["status"]): NodeVisualStatus {
  if (s === "failed") return "failed";
  if (s === "started") return "active";
  return "done"; // completed | skipped
}

/** Latest-log-wins per node; current (paused) nodes are forced to "active". */
export function computeNodeStatuses(
  logs: NodeLogDTO[],
  currentNodeIds: string[],
): Record<string, NodeVisualStatus> {
  const out: Record<string, NodeVisualStatus> = {};
  const latestAt: Record<string, string> = {};
  for (const l of logs) {
    if (!(l.node_id in latestAt) || new Date(l.started_at).getTime() >= new Date(latestAt[l.node_id]).getTime()) {
      latestAt[l.node_id] = l.started_at;
      out[l.node_id] = mapLogStatus(l.status);
    }
  }
  for (const nid of currentNodeIds) out[nid] = "active";
  return out;
}

/** An edge is "taken" when its source completed and its target has been reached. */
export function computeTakenEdges(
  statuses: Record<string, NodeVisualStatus>,
  edges: { id: string; source: string; target: string }[],
): string[] {
  const reached = (s?: NodeVisualStatus) => s === "done" || s === "active" || s === "failed";
  return edges
    .filter((e) => statuses[e.source] === "done" && reached(statuses[e.target]))
    .map((e) => e.id);
}
