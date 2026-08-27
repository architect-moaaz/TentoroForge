"use client";

import {
  Zap,
  Play,
  GitBranch,
  Clock,
  Square,
  UserPlus,
  CheckCircle,
  Users,
  ArrowUpCircle,
  Brain,
  ScanText,
  Sparkles,
  Hand,
  Webhook,
  Calendar,
  Database,
  Globe,
  Mail,
  Bell,
  Table2,
  Split,
  GitMerge,
  Hash,
  FileText,
} from "lucide-react";
import { NODE_CATEGORIES, type WorkflowNodeType } from "@/types/workflow";

const ICONS: Record<string, typeof Zap> = {
  Zap,
  Play,
  GitBranch,
  Clock,
  Square,
  UserPlus,
  CheckCircle,
  Users,
  ArrowUpCircle,
  Brain,
  ScanText,
  Sparkles,
  Hand,
  Webhook,
  Calendar,
  Database,
  Globe,
  Mail,
  Bell,
  Table2,
  Split,
  GitMerge,
  Hash,
  FileText,
};

export function NodePalette() {
  const onDragStart = (
    event: React.DragEvent,
    nodeType: WorkflowNodeType,
    label: string,
    defaultConfig?: Record<string, unknown>,
  ) => {
    event.dataTransfer.setData("application/workflow-node-type", nodeType);
    event.dataTransfer.setData("application/workflow-node-label", label);
    if (defaultConfig) {
      event.dataTransfer.setData(
        "application/workflow-node-config",
        JSON.stringify(defaultConfig),
      );
    }
    event.dataTransfer.effectAllowed = "move";
  };

  return (
    <div className="flex shrink-0 flex-col border-r bg-muted/20 w-[240px] overflow-y-auto">
      <div className="border-b px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Node Palette
        </span>
      </div>
      {NODE_CATEGORIES.map((category) => (
        <div key={category.label}>
          <div className="border-b border-gray-100 px-4 py-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {category.label}
            </span>
          </div>
          {category.nodes.map((node) => {
            const Icon = ICONS[node.icon] || Play;
            return (
              <div
                key={node.id}
                className="flex cursor-grab items-center gap-3 px-3 py-2.5 hover:bg-muted/50 active:cursor-grabbing"
                draggable
                onDragStart={(e) =>
                  onDragStart(
                    e,
                    node.type,
                    node.label,
                    node.defaultConfig as Record<string, unknown> | undefined,
                  )
                }
              >
                <div
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${node.gradient}`}
                >
                  <Icon className="h-4 w-4 text-white" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-slate-800">
                    {node.label}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {node.description}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
