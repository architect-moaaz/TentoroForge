"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Home, AlertTriangle, Layout, PanelLeft, Menu } from "lucide-react";
import type { ScreenNodeData } from "@/types/navigation";

const LAYOUT_ICONS = {
  sidebar: PanelLeft,
  topnav: Menu,
  blank: Layout,
} as const;

export const ScreenNode = memo(function ScreenNode({
  data,
  selected,
}: NodeProps & { data: ScreenNodeData }) {
  const LayoutIcon = LAYOUT_ICONS[data.layout || "blank"] || Layout;

  return (
    <div
      className={`rounded-lg border bg-white shadow-sm transition-shadow ${
        selected ? "ring-2 ring-blue-400 shadow-md" : ""
      } ${data.isDefault ? "border-green-400" : ""} ${
        data.isError ? "border-red-400" : ""
      }`}
      style={{ minWidth: 160 }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />

      {/* Header */}
      <div className="flex items-center gap-1.5 border-b px-3 py-1.5">
        {data.isDefault && <Home className="h-3 w-3 text-green-600" />}
        {data.isError && <AlertTriangle className="h-3 w-3 text-red-500" />}
        <LayoutIcon className="h-3 w-3 text-muted-foreground" />
        <span className="text-xs font-medium truncate flex-1">
          {data.label}
        </span>
      </div>

      {/* Route */}
      <div className="px-3 py-2">
        <p className="text-[10px] font-mono text-muted-foreground">
          {data.route}
        </p>

        {/* Page thumbnail placeholder */}
        <div className="mt-1.5 h-16 rounded bg-gray-50 border border-dashed flex items-center justify-center">
          <span className="text-[9px] text-gray-300">Preview</span>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-gray-400"
      />
    </div>
  );
});
