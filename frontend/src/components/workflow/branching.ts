/**
 * Which node types fork into `then` / `else`?
 *
 * A14-2: this list was hardcoded in TWO places that had drifted apart from a
 * third:
 *   - WorkflowCanvas.onConnect       decided whether a new edge is typed `then`
 *   - nodes/WorkflowNode             decided whether to render an `else` handle
 *   - the runtime engine             already treated exclusive_gateway as a
 *                                    condition
 *
 * `exclusive_gateway` was in the engine's list but neither of the editor's, so
 * its edges saved as `default` and there was no else handle to drag from — a
 * two-branch gateway could not be authored at all, and the run still reported
 * `completed`.
 *
 * One exported predicate so the two editor sites cannot drift again.
 */
export const BRANCHING_NODE_TYPES = [
  "condition",
  "decision",
  "ai_decide",
  "exclusive_gateway",
] as const;

export function isBranchingNode(nodeType: string | undefined): boolean {
  return !!nodeType && (BRANCHING_NODE_TYPES as readonly string[]).includes(nodeType);
}
