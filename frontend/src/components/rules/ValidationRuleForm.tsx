"use client";

import { useState } from "react";
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
import type { ConditionExpression, RuleConfig } from "@/types/rules";

interface ValidationRuleFormProps {
  modelNames: string[];
  fieldNames: string[];
  config: RuleConfig;
  modelName: string;
  fieldName: string;
  onConfigChange: (config: RuleConfig) => void;
  onModelChange: (model: string) => void;
  onFieldChange: (field: string) => void;
}

export function ValidationRuleForm({
  modelNames,
  fieldNames,
  config,
  modelName,
  fieldName,
  onConfigChange,
  onModelChange,
  onFieldChange,
}: ValidationRuleFormProps) {
  const enforcement = config.enforcement || ["api"];

  const toggleEnforcement = (target: "api" | "ui" | "db") => {
    const current = new Set(enforcement);
    if (current.has(target)) {
      current.delete(target);
    } else {
      current.add(target);
    }
    onConfigChange({ ...config, enforcement: Array.from(current) as ("api" | "ui" | "db")[] });
  };

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
          <Label className="text-xs">Field</Label>
          <Select value={fieldName || "__none__"} onValueChange={(v) => onFieldChange(v === "__none__" ? "" : v)}>
            <SelectTrigger className="mt-1 h-8 text-xs">
              <SelectValue placeholder="Select field..." />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__" className="text-xs">All fields</SelectItem>
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
        <Label className="text-xs">Error Message</Label>
        <Input
          className="mt-1 h-8 text-xs"
          placeholder="Validation failed..."
          value={config.errorMessage || ""}
          onChange={(e) => onConfigChange({ ...config, errorMessage: e.target.value })}
        />
      </div>

      <div>
        <Label className="text-xs">Enforce At</Label>
        <div className="mt-1 flex gap-2">
          {(["api", "ui", "db"] as const).map((target) => (
            <button
              key={target}
              type="button"
              className={`rounded-md border px-3 py-1 text-xs ${
                enforcement.includes(target)
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "border-muted text-muted-foreground hover:bg-muted/50"
              }`}
              onClick={() => toggleEnforcement(target)}
            >
              {target.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
