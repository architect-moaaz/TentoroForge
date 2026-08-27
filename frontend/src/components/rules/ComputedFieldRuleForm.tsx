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
import type { RuleConfig } from "@/types/rules";

interface ComputedFieldRuleFormProps {
  modelNames: string[];
  fieldNames: string[];
  config: RuleConfig;
  modelName: string;
  onConfigChange: (config: RuleConfig) => void;
  onModelChange: (model: string) => void;
}

export function ComputedFieldRuleForm({
  modelNames,
  fieldNames,
  config,
  modelName,
  onConfigChange,
  onModelChange,
}: ComputedFieldRuleFormProps) {
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
          <Label className="text-xs">Target Field</Label>
          <Select
            value={config.targetField || "__none__"}
            onValueChange={(v) =>
              onConfigChange({ ...config, targetField: v === "__none__" ? "" : v })
            }
          >
            <SelectTrigger className="mt-1 h-8 text-xs">
              <SelectValue placeholder="Select field..." />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__" className="text-xs">New field...</SelectItem>
              {fieldNames.map((f) => (
                <SelectItem key={f} value={f} className="text-xs">{f}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {(!config.targetField || config.targetField === "") && (
        <div>
          <Label className="text-xs">New Field Name</Label>
          <Input
            className="mt-1 h-8 text-xs"
            placeholder="e.g. full_name, total_amount"
            value={config.targetField || ""}
            onChange={(e) => onConfigChange({ ...config, targetField: e.target.value })}
          />
        </div>
      )}

      <div>
        <Label className="text-xs">Expression</Label>
        <p className="text-[10px] text-muted-foreground mb-1">
          Reference fields using their names. Example: first_name + &apos; &apos; + last_name
        </p>
        <Input
          className="mt-1 h-8 text-xs font-mono"
          placeholder="e.g. quantity * unit_price"
          value={config.expression || ""}
          onChange={(e) => onConfigChange({ ...config, expression: e.target.value })}
        />
        {fieldNames.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {fieldNames.map((f) => (
              <button
                key={f}
                type="button"
                className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted/50"
                onClick={() =>
                  onConfigChange({
                    ...config,
                    expression: (config.expression || "") + f,
                  })
                }
              >
                {f}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
