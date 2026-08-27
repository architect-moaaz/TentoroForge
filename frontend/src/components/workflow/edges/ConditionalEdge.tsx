"use client";

import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
  EdgeLabelRenderer,
} from "@xyflow/react";
import type { WorkflowEdgeData, WorkflowEdgeType } from "@/types/workflow";

const EDGE_STYLES: Record<WorkflowEdgeType, { stroke: string; strokeDasharray?: string; label?: string }> = {
  default: { stroke: "#94a3b8" },
  then:    { stroke: "#22c55e", strokeDasharray: "6 3", label: "Yes" },
  else:    { stroke: "#ef4444", strokeDasharray: "6 3", label: "No" },
  error:   { stroke: "#f97316", strokeDasharray: "3 3", label: "Error" },
};

export function ConditionalEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  markerEnd,
  style: styleProp,
}: EdgeProps & { data?: WorkflowEdgeData }) {
  const edgeType: WorkflowEdgeType = data?.edgeType || "default";
  // Runtime guard: WorkflowEdgeType is compile-time only. If a workflow JSON
  // carries an unknown edgeType (e.g. from a new emitter that predates a
  // union bump), `EDGE_STYLES[edgeType]` returns undefined and every field
  // access below throws. Fall back to the default style — safer than
  // crashing the whole ProjectWorkspace when Smith emits a novel edge.
  const edgeStyle = EDGE_STYLES[edgeType] ?? EDGE_STYLES.default;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const label = data?.label || edgeStyle.label;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: edgeStyle.stroke,
          strokeWidth: 2.5,
          strokeDasharray: edgeStyle.strokeDasharray,
          // C2: merge caller-provided style (e.g. taken-edge amber highlight) over base style
          ...styleProp,
        }}
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none absolute rounded-full bg-white px-2.5 py-0.5 text-[11px] font-semibold shadow-sm border"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              color: edgeStyle.stroke,
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
