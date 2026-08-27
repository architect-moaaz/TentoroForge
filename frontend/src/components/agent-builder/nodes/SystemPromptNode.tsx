"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Brain } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AgentNodeData, SystemPromptConfig } from "@/types/agent-builder";

function SystemPromptNodeComponent({ data, selected }: NodeProps & { data: AgentNodeData }) {
  const { label, config } = data;
  const cfg = config as SystemPromptConfig;
  const promptPreview = cfg.prompt ? cfg.prompt.slice(0, 60) + (cfg.prompt.length > 60 ? "..." : "") : "";

  return (
    <div
      className={`min-w-[160px] max-w-[220px] rounded-lg border-2 border-purple-400 bg-purple-50 shadow-sm ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""
      }`}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <Brain className="h-4 w-4 shrink-0 text-purple-600" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className="truncate text-xs font-semibold text-slate-800">{label}</div>
            {cfg.is_entry_point && (
              <Badge variant="secondary" className="text-[8px] px-1 py-0">Default</Badge>
            )}
          </div>
          {promptPreview && (
            <div className="truncate text-[10px] text-slate-500">{promptPreview}</div>
          )}
        </div>
      </div>

      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !bg-purple-400 !border-white !border-2"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !bg-purple-400 !border-white !border-2"
      />
    </div>
  );
}

export const SystemPromptNode = memo(SystemPromptNodeComponent);
