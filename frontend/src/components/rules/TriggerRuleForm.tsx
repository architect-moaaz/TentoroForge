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

interface TriggerRuleFormProps {
  modelNames: string[];
  fieldNames: string[];
  config: RuleConfig;
  modelName: string;
  fieldName: string;
  onConfigChange: (config: RuleConfig) => void;
  onModelChange: (model: string) => void;
  onFieldChange: (field: string) => void;
}

export function TriggerRuleForm({
  modelNames,
  fieldNames,
  config,
  modelName,
  fieldName,
  onConfigChange,
  onModelChange,
  onFieldChange,
}: TriggerRuleFormProps) {
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
          <Label className="text-xs">Watch Field</Label>
          <Select
            value={fieldName || config.watchField || "__none__"}
            onValueChange={(v) => {
              const val = v === "__none__" ? "" : v;
              onFieldChange(val);
              onConfigChange({ ...config, watchField: val });
            }}
          >
            <SelectTrigger className="mt-1 h-8 text-xs">
              <SelectValue placeholder="Select field..." />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__" className="text-xs">Any field</SelectItem>
              {fieldNames.map((f) => (
                <SelectItem key={f} value={f} className="text-xs">{f}</SelectItem>
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
        <Label className="text-xs">Action Description</Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder="e.g. Send email notification, Call webhook, Update related field..."
          value={config.actionDescription || ""}
          onChange={(e) =>
            onConfigChange({ ...config, actionDescription: e.target.value })
          }
        />
      </div>
    </div>
  );
}
