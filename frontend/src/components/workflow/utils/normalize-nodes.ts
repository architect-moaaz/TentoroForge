import type { WorkflowNodeSerialized } from "@/types/workflow";

// AI capabilities exist in the runtime as BOTH top-level node types and action
// subtypes. The canonical editor representation is the top-level node type
// (`ai_generate`), but older/generated workflows emit them in the legacy action
// shape (`type: "action"`, `config.actionType: "ai_generate"`). Left as-is, the
// canvas would need a special-case and the properties panel — which switches on
// `data.nodeType` — would render a generic Action editor instead of the AI one.
const _AI_TYPES = new Set(["ai_generate", "ai_classify", "ai_extract", "ai_decide"]);

/**
 * Promote legacy `action:ai_*` nodes to their canonical top-level node type on load,
 * so every editor surface (canvas visual, properties panel, palette match) treats a
 * generated AI node exactly like a hand-placed one. Non-AI actions (db_update,
 * set_variable, …) are left untouched — those are genuinely action subtypes.
 * Pure + non-mutating.
 */
export function normalizeWorkflowNodes(
  nodes: WorkflowNodeSerialized[] | undefined | null,
): WorkflowNodeSerialized[] {
  if (!Array.isArray(nodes)) return [];
  return nodes.map((raw) => {
    // The top-level `type` is the canonical node type (the engine dispatches on
    // it); `data.nodeType` is the editor's copy, which the canvas and the
    // properties panel switch on. A node written without the copy would render
    // as React Flow's unstyled default box, so fill it from the canonical field.
    const node: WorkflowNodeSerialized =
      raw?.data && !raw.data.nodeType && raw.type
        ? { ...raw, data: { ...raw.data, nodeType: raw.type as WorkflowNodeSerialized["data"]["nodeType"] } }
        : raw;
    const at = node?.data?.config?.actionType;
    const isLegacyAiAction =
      (node?.type === "action" || node?.data?.nodeType === "action") &&
      typeof at === "string" &&
      _AI_TYPES.has(at);
    if (!isLegacyAiAction) return node;
    return {
      ...node,
      type: at as string,
      data: { ...node.data, nodeType: at as WorkflowNodeSerialized["data"]["nodeType"] },
    };
  });
}
