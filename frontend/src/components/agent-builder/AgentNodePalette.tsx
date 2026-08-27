"use client";

import {
  Brain,
  Wrench,
  Shield,
  DatabaseZap,
  GitFork,
  UserCheck,
} from "lucide-react";
import { AGENT_NODE_CATEGORIES, type AgentNodeType } from "@/types/agent-builder";

const ICONS: Record<string, typeof Brain> = {
  Brain,
  Wrench,
  Shield,
  DatabaseZap,
  GitFork,
  UserCheck,
};

export function AgentNodePalette() {
  const onDragStart = (
    event: React.DragEvent,
    nodeType: AgentNodeType,
    label: string,
  ) => {
    event.dataTransfer.setData("application/agent-node-type", nodeType);
    event.dataTransfer.setData("application/agent-node-label", label);
    event.dataTransfer.effectAllowed = "move";
  };

  return (
    <div className="flex shrink-0 flex-col border-r bg-muted/20 w-[180px] overflow-y-auto">
      <div className="border-b px-3 py-2">
        <span className="text-xs font-semibold uppercase text-muted-foreground">
          Agent Nodes
        </span>
      </div>
      {AGENT_NODE_CATEGORIES.map((category) => (
        <div key={category.label}>
          <div className="px-3 py-1.5">
            <span className="text-[10px] font-semibold uppercase text-muted-foreground">
              {category.label}
            </span>
          </div>
          {category.nodes.map((node) => {
            const Icon = ICONS[node.icon] || Brain;
            return (
              <div
                key={node.type}
                className="flex cursor-grab items-center gap-2 px-3 py-1.5 text-xs hover:bg-muted/50 active:cursor-grabbing"
                draggable
                onDragStart={(e) => onDragStart(e, node.type, node.label)}
                title={node.description}
              >
                <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span>{node.label}</span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
