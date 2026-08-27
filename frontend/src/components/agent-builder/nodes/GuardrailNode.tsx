"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Shield } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AgentNodeData, GuardrailConfig } from "@/types/agent-builder";

function GuardrailNodeComponent({ data, selected }: NodeProps & { data: AgentNodeData }) {
  const { label, config } = data;
  const cfg = config as GuardrailConfig;
  const subtitle = cfg.guardrail_type || "";
  const ruleCount = cfg.rules?.length || 0;

  return (
    <div
      className={`min-w-[160px] max-w-[220px] rounded-lg border-2 border-orange-400 bg-orange-50 shadow-sm ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""
      }`}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <Shield className="h-4 w-4 shrink-0 text-orange-600" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className="truncate text-xs font-semibold text-slate-800">{label}</div>
            {ruleCount > 0 && (
              <Badge variant="secondary" className="text-[8px] px-1 py-0">
                {ruleCount} rule{ruleCount !== 1 ? "s" : ""}
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
        className="!w-2.5 !h-2.5 !bg-orange-400 !border-white !border-2"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !bg-orange-400 !border-white !border-2"
      />
    </div>
  );
}

export const GuardrailNode = memo(GuardrailNodeComponent);
