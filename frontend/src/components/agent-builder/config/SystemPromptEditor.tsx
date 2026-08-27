"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { SystemPromptConfig } from "@/types/agent-builder";

interface SystemPromptEditorProps {
  config: SystemPromptConfig;
  onUpdate: (config: Partial<SystemPromptConfig>) => void;
}

export function SystemPromptEditor({ config, onUpdate }: SystemPromptEditorProps) {
  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">System Prompt</Label>
        <Textarea
          className="mt-1 text-xs min-h-[100px] resize-y"
          placeholder="You are a helpful assistant that..."
          value={config.prompt || ""}
          onChange={(e) => onUpdate({ prompt: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-xs">Model</Label>
        <Select
          value={config.model || "gpt-4o"}
          onValueChange={(v) => onUpdate({ model: v })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="gpt-4o" className="text-xs">GPT-4o</SelectItem>
            <SelectItem value="gpt-4o-mini" className="text-xs">GPT-4o Mini</SelectItem>
            <SelectItem value="claude-sonnet-4-6" className="text-xs">Claude Sonnet 4.6</SelectItem>
            <SelectItem value="claude-haiku-4-5" className="text-xs">Claude Haiku 4.5</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label className="text-xs">
          Temperature: {config.temperature ?? 0.7}
        </Label>
        <Slider
          className="mt-2"
          min={0}
          max={2}
          step={0.1}
          value={[config.temperature ?? 0.7]}
          onValueChange={([v]) => onUpdate({ temperature: v })}
        />
      </div>
      <div>
        <Label className="text-xs">Max Tokens</Label>
        <Input
          className="mt-1 h-8 text-xs"
          type="number"
          placeholder="4096"
          value={config.max_tokens || ""}
          onChange={(e) =>
            onUpdate({ max_tokens: e.target.value ? parseInt(e.target.value) : undefined })
          }
        />
      </div>
      <div className="flex items-center gap-2">
        <Switch
          checked={config.is_entry_point || false}
          onCheckedChange={(v) => onUpdate({ is_entry_point: v })}
        />
        <Label className="text-xs">Entry Point (Default)</Label>
      </div>
    </div>
  );
}
