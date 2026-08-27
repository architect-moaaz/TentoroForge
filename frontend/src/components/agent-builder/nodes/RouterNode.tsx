"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { GitFork } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { AgentNodeData, RouterConfig } from "@/types/agent-builder";

function RouterNodeComponent({ data, selected }: NodeProps & { data: AgentNodeData }) {
  const { label, config } = data;
  const cfg = config as RouterConfig;
  const subtitle = cfg.strategy || "";
  const routeCount = cfg.routes?.length || 0;

  return (
    <div
      className={`min-w-[160px] max-w-[220px] rounded-lg border-2 border-teal-400 bg-teal-50 shadow-sm ${
        selected ? "ring-2 ring-indigo-500 ring-offset-1" : ""
      }`}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <GitFork className="h-4 w-4 shrink-0 text-teal-600" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <div className="truncate text-xs font-semibold text-slate-800">{label}</div>
            {routeCount > 0 && (
              <Badge variant="secondary" className="text-[8px] px-1 py-0">
                {routeCount} route{routeCount !== 1 ? "s" : ""}
              </Badge>
            )}
          </div>
          {subtitle && (
            <div className="truncate text-[10px] text-slate-500">{subtitle}</div>
          )}
        </div>
      </div>

      {/* Target handle (input) */}
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !bg-teal-400 !border-white !border-2"
      />
      {/* Default output handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="default"
        className="!w-2.5 !h-2.5 !bg-teal-400 !border-white !border-2"
        style={{ top: "30%" }}
      />
      {/* Additional output handles for routes */}
      {routeCount > 0 && (
        <Handle
          type="source"
          position={Position.Right}
          id="route_1"
          className="!w-2.5 !h-2.5 !bg-teal-300 !border-white !border-2"
          style={{ top: "60%" }}
        />
      )}
      {routeCount > 1 && (
        <Handle
          type="source"
          position={Position.Bottom}
          id="route_2"
          className="!w-2.5 !h-2.5 !bg-teal-300 !border-white !border-2"
        />
      )}
    </div>
  );
}

export const RouterNode = memo(RouterNodeComponent);
