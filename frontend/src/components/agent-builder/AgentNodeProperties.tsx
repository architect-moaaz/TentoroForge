"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { SystemPromptEditor } from "./config/SystemPromptEditor";
import { ToolPicker } from "./config/ToolPicker";
import { GuardrailEditor } from "./config/GuardrailEditor";
import { MemoryEditor } from "./config/MemoryEditor";
import { HandoffEditor } from "./config/HandoffEditor";
import { RouterEditor } from "./config/RouterEditor";
import type {
  AgentNodeData,
  AgentNodeConfig,
  SystemPromptConfig,
  ToolConfig,
  GuardrailConfig,
  MemoryConfig,
  HumanHandoffConfig,
  RouterConfig,
} from "@/types/agent-builder";

interface AgentNodePropertiesProps {
  nodeData: AgentNodeData;
  nodeId: string;
  onUpdate: (data: Partial<AgentNodeData>) => void;
  onClose: () => void;
  projectId?: string;
  orgId?: string;
}

export function AgentNodeProperties({
  nodeData,
  nodeId,
  onUpdate,
  onClose,
  projectId,
  orgId,
}: AgentNodePropertiesProps) {
  const { label, nodeType, config } = nodeData;

  const updateConfig = (updates: Partial<AgentNodeConfig>) => {
    onUpdate({ config: { ...config, ...updates } });
  };

  return (
    <div className="flex w-[280px] shrink-0 flex-col border-l bg-white overflow-y-auto">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-xs font-semibold">Properties</span>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>

      <div className="space-y-4 p-3">
        {/* Common: Label */}
        <div>
          <Label className="text-xs">Label</Label>
          <Input
            className="mt-1 h-8 text-xs"
            value={label}
            onChange={(e) => onUpdate({ label: e.target.value })}
          />
        </div>

        <Separator />

        {/* Type-specific property editors */}
        {nodeType === "system_prompt" && (
          <SystemPromptEditor
            config={config as SystemPromptConfig}
            onUpdate={updateConfig}
          />
        )}
        {nodeType === "tool" && (
          <ToolPicker
            config={config as ToolConfig}
            onUpdate={updateConfig}
            projectId={projectId}
            orgId={orgId}
          />
        )}
        {nodeType === "guardrail" && (
          <GuardrailEditor
            config={config as GuardrailConfig}
            onUpdate={updateConfig}
          />
        )}
        {nodeType === "memory" && (
          <MemoryEditor
            config={config as MemoryConfig}
            onUpdate={updateConfig}
          />
        )}
        {nodeType === "human_handoff" && (
          <HandoffEditor
            config={config as HumanHandoffConfig}
            onUpdate={updateConfig}
          />
        )}
        {nodeType === "router" && (
          <RouterEditor
            config={config as RouterConfig}
            onUpdate={updateConfig}
          />
        )}

        <Separator />
        <p className="text-[10px] text-muted-foreground">
          Node ID: {nodeId}
        </p>
      </div>
    </div>
  );
}
