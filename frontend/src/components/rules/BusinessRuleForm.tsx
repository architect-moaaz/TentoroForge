"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConditionBuilder } from "./ConditionBuilder";
import type { RuleConfig } from "@/types/rules";

interface BusinessRuleFormProps {
  modelNames: string[];
  fieldNames: string[];
  config: RuleConfig;
  modelName: string;
  onConfigChange: (config: RuleConfig) => void;
  onModelChange: (model: string) => void;
}

const TRIGGER_ACTIONS = [
  { value: "create", label: "Create" },
  { value: "update", label: "Update" },
  { value: "delete", label: "Delete" },
  { value: "create_update", label: "Create or Update" },
];

export function BusinessRuleForm({
  modelNames,
  fieldNames,
  config,
  modelName,
  onConfigChange,
  onModelChange,
}: BusinessRuleFormProps) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs">Model</Label>
          <Select value={modelName} onValueChange={onModelChange}>
            <SelectTrigger className="mt-1 h-8 text-xs">
              <SelectValue placeholder="Select model..." />
            </SelectTrigger>
            <SelectContent>
              {modelNames.map((m) => (
                <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">Trigger Action</Label>
          <Select
            value={config.triggerAction || "create_update"}
            onValueChange={(v) => onConfigChange({ ...config, triggerAction: v })}
          >
            <SelectTrigger className="mt-1 h-8 text-xs">
              <SelectValue placeholder="Select trigger..." />
            </SelectTrigger>
            <SelectContent>
              {TRIGGER_ACTIONS.map((a) => (
                <SelectItem key={a.value} value={a.value} className="text-xs">
                  {a.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <ConditionBuilder
        value={config.condition || null}
        onChange={(c) => onConfigChange({ ...config, condition: c || undefined })}
        fields={fieldNames}
      />

      <div>
        <Label className="text-xs">Consequence</Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder="Describe what should happen when the condition is met..."
          value={config.consequence || ""}
          onChange={(e) => onConfigChange({ ...config, consequence: e.target.value })}
        />
      </div>
    </div>
  );
}
