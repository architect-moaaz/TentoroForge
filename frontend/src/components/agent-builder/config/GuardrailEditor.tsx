"use client";

import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { GuardrailConfig, GuardrailType, GuardrailRule } from "@/types/agent-builder";

interface GuardrailEditorProps {
  config: GuardrailConfig;
  onUpdate: (config: Partial<GuardrailConfig>) => void;
}

export function GuardrailEditor({ config, onUpdate }: GuardrailEditorProps) {
  const addRule = () => {
    const rules = config.rules || [];
    onUpdate({
      rules: [
        ...rules,
        { id: `rule_${Date.now()}`, name: "", type: "content_policy" },
      ],
    });
  };

  const updateRule = (index: number, updates: Partial<GuardrailRule>) => {
    const rules = [...(config.rules || [])];
    rules[index] = { ...rules[index], ...updates };
    onUpdate({ rules });
  };

  const removeRule = (index: number) => {
    const rules = [...(config.rules || [])];
    rules.splice(index, 1);
    onUpdate({ rules });
  };

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-xs">Filter Type</Label>
        <Select
          value={config.guardrail_type || "both"}
          onValueChange={(v) => onUpdate({ guardrail_type: v as GuardrailType })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="input_filter" className="text-xs">Input Filter</SelectItem>
            <SelectItem value="output_filter" className="text-xs">Output Filter</SelectItem>
            <SelectItem value="both" className="text-xs">Both (Input + Output)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Rules */}
      <div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">Rules</Label>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={addRule}>
            <Plus className="h-3 w-3 mr-0.5" />
            Add Rule
          </Button>
        </div>
        <div className="mt-1 space-y-2">
          {(config.rules || []).map((rule, i) => (
            <div key={rule.id} className="rounded border p-2 space-y-1.5">
              <div className="flex items-center gap-1">
                <Input
                  className="h-7 text-[10px] flex-1"
                  placeholder="Rule name"
                  value={rule.name}
                  onChange={(e) => updateRule(i, { name: e.target.value })}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => removeRule(i)}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
              <Select
                value={rule.type}
                onValueChange={(v) =>
                  updateRule(i, { type: v as GuardrailRule["type"] })
                }
              >
                <SelectTrigger className="h-7 text-[10px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="block_topics" className="text-[10px]">Block Topics</SelectItem>
                  <SelectItem value="pii_redaction" className="text-[10px]">PII Redaction</SelectItem>
                  <SelectItem value="content_policy" className="text-[10px]">Content Policy</SelectItem>
                  <SelectItem value="custom" className="text-[10px]">Custom</SelectItem>
                </SelectContent>
              </Select>
              {rule.type === "custom" && (
                <Input
                  className="h-7 text-[10px] font-mono"
                  placeholder="Custom expression..."
                  value={rule.expression || ""}
                  onChange={(e) => updateRule(i, { expression: e.target.value })}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        <Label className="text-xs">Custom Expression (Global)</Label>
        <Textarea
          className="mt-1 text-xs font-mono min-h-[50px]"
          placeholder="Optional global guardrail expression..."
          value={config.custom_expression || ""}
          onChange={(e) => onUpdate({ custom_expression: e.target.value })}
        />
      </div>
    </div>
  );
}
