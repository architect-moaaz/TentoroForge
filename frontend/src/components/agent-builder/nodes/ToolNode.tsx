"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AgentNodeData, ToolConfig } from "@/types/agent-builder";

function ToolNodeComponent({ data, selected }: NodeProps & { data: AgentNodeData }) {
  const { label, config } = data;
  const cfg = config as ToolConfig;
  const subtitle = cfg.tool_name || cfg.tool_type || "";
  const paramCount = cfg.parameters?.length || 0;

  return (
    <div
      className={`min-w-[160px] max-w-[220px] rounded-lg border-2 border-blue-400 bg-blue-50 shadow-sm ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""
      }`}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <Wrench className="h-4 w-4 shrink-0 text-blue-600" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className="truncate text-xs font-semibold text-slate-800">{label}</div>
            {paramCount > 0 && (
              <Badge variant="secondary" className="text-[8px] px-1 py-0">
                {paramCount} param{paramCount !== 1 ? "s" : ""}
              </Badge>
            )}
          </div>
          {subtitle && (
            <div className="truncate text-[10px] text-slate-500">{subtitle}</div>
          )}
        </div>
      </div>

      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !bg-blue-400 !border-white !border-2"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !bg-blue-400 !border-white !border-2"
      />
    </div>
  );
}

export const ToolNode = memo(ToolNodeComponent);
