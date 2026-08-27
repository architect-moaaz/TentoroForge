"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { HumanHandoffConfig } from "@/types/agent-builder";

interface HandoffEditorProps {
  config: HumanHandoffConfig;
  onUpdate: (config: Partial<HumanHandoffConfig>) => void;
}

export function HandoffEditor({ config, onUpdate }: HandoffEditorProps) {
  const conditions = config.conditions || {};
  const target = config.target || {};

  const updateConditions = (updates: Partial<typeof conditions>) => {
    onUpdate({ conditions: { ...conditions, ...updates } });
  };

  const updateTarget = (updates: Partial<typeof target>) => {
    onUpdate({ target: { ...target, ...updates } });
  };

  return (
    <div className="space-y-3">
      <p className="text-[10px] font-semibold text-muted-foreground uppercase">
        Escalation Conditions
      </p>
      <div>
        <Label className="text-xs">Sentiment Threshold</Label>
        <Input
          className="mt-1 h-8 text-xs"
          type="number"
          placeholder="0.3 (lower = more sensitive)"
          step="0.1"
          min="0"
          max="1"
          value={conditions.sentiment_threshold ?? ""}
          onChange={(e) =>
            updateConditions({
              sentiment_threshold: e.target.value ? parseFloat(e.target.value) : undefined,
            })
          }
        />
      </div>
      <div>
        <Label className="text-xs">Keyword Triggers</Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder="help, agent, human, speak to someone"
          value={(conditions.keyword_triggers || []).join(", ")}
          onChange={(e) =>
            updateConditions({
              keyword_triggers: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
        <p className="text-[10px] text-muted-foreground mt-0.5">Comma-separated keywords</p>
      </div>
      <div className="flex items-center gap-2">
        <Switch
          checked={conditions.explicit_request || false}
          onCheckedChange={(v) => updateConditions({ explicit_request: v })}
        />
        <Label className="text-xs">Trigger on explicit request</Label>
      </div>

      <p className="text-[10px] font-semibold text-muted-foreground uppercase pt-2">
        Handoff Target
      </p>
      <div>
        <Label className="text-xs">Target Type</Label>
        <Select
          value={target.type || "queue"}
          onValueChange={(v) => updateTarget({ type: v as "queue" | "email" | "webhook" })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="queue" className="text-xs">Human Queue</SelectItem>
            <SelectItem value="email" className="text-xs">Email</SelectItem>
            <SelectItem value="webhook" className="text-xs">Webhook</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label className="text-xs">
          {target.type === "email" ? "Email Address" : target.type === "webhook" ? "Webhook URL" : "Queue Name"}
        </Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder={
            target.type === "email"
              ? "support@example.com"
              : target.type === "webhook"
                ? "https://hooks.example.com/handoff"
                : "support-queue"
          }
          value={target.value || ""}
          onChange={(e) => updateTarget({ value: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs">Context Fields to Pass</Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder="user_id, conversation_id, topic"
          value={(config.context_fields || []).join(", ")}
          onChange={(e) =>
            onUpdate({
              context_fields: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
      </div>
    </div>
  );
}
