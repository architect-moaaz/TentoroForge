"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { DatabaseZap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AgentNodeData, MemoryConfig } from "@/types/agent-builder";

function MemoryNodeComponent({ data, selected }: NodeProps & { data: AgentNodeData }) {
  const { label, config } = data;
  const cfg = config as MemoryConfig;
  const subtitle = cfg.memory_type || "";
  const capacityLabel = cfg.capacity ? `${cfg.capacity}` : "";

  return (
    <div
      className={`min-w-[160px] max-w-[220px] rounded-lg border-2 border-green-400 bg-green-50 shadow-sm ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""
      }`}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <DatabaseZap className="h-4 w-4 shrink-0 text-green-600" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className="truncate text-xs font-semibold text-slate-800">{label}</div>
            {capacityLabel && (
              <Badge variant="secondary" className="text-[8px] px-1 py-0">
                cap: {capacityLabel}
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
        className="!w-2.5 !h-2.5 !bg-green-400 !border-white !border-2"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !bg-green-400 !border-white !border-2"
      />
    </div>
  );
}

export const MemoryNode = memo(MemoryNodeComponent);
