/**
 * Generate a stable synthetic node id from a node's type + serialised props.
 * Used when legacy schemas omit explicit ids on nested nodes — the renderer
 * needs SOME id for data-node-id (for the selection overlay) and the editor's
 * findNodeInArtifacts walk.
 *
 * Stability requirement: same (type, props) MUST produce the same id every
 * time — across the renderer + editor + standalone app — so synthetic ids
 * match between the rendered DOM's data-node-id and the editor store's
 * selection state.
 *
 * Algorithm: djb2 variant — `h = ((h << 5) - h + charCode) | 0`.
 * Fast, deterministic, sufficient for uniqueness within a single schema tree.
 * Matches the original implementations in dispatch.tsx and Canvas.tsx exactly.
 */

export function syntheticNodeId(node: {
  type?: string;
  props?: Record<string, unknown>;
}): string {
  const type = node?.type ?? "unknown";
  const key = type + JSON.stringify(node?.props ?? {});
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = ((h << 5) - h + key.charCodeAt(i)) | 0;
  }
  return `${type}_${(h >>> 0).toString(16)}`;
}
