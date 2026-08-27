"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { UserCheck } from "lucide-react";
import type { AgentNodeData, HumanHandoffConfig } from "@/types/agent-builder";

function HumanHandoffNodeComponent({ data, selected }: NodeProps & { data: AgentNodeData }) {
  const { label, config } = data;
  const cfg = config as HumanHandoffConfig;
  const conditions = cfg.conditions || {};
  const subtitle = conditions.keyword_triggers?.length
    ? conditions.keyword_triggers.slice(0, 2).join(", ")
    : conditions.explicit_request
      ? "On explicit request"
      : "";

  return (
    <div
      className={`min-w-[160px] max-w-[220px] rounded-lg border-2 border-yellow-400 bg-yellow-50 shadow-sm ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""
      }`}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <UserCheck className="h-4 w-4 shrink-0 text-yellow-600" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-semibold text-slate-800">{label}</div>
          {subtitle && (
            <div className="truncate text-[10px] text-slate-500">{subtitle}</div>
          )}
        </div>
      </div>

      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !bg-yellow-400 !border-white !border-2"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !bg-yellow-400 !border-white !border-2"
      />
    </div>
  );
}

export const HumanHandoffNode = memo(HumanHandoffNodeComponent);
