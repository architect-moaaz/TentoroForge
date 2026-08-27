"use client";

/**
 * ProcessVariablesEditor — edits workflow-level process variables.
 *
 * Shown when no node is selected (workflow-level config).
 * Add/remove/edit variables that flow through the workflow.
 */

import { useState } from "react";
import { Plus, Trash2, GripVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ProcessVariable } from "@/types/workflow";

interface ProcessVariablesEditorProps {
  variables: ProcessVariable[];
  onChange: (variables: ProcessVariable[]) => void;
}

const VAR_TYPES = ["string", "number", "boolean", "object", "array", "date"] as const;

export function ProcessVariablesEditor({ variables, onChange }: ProcessVariablesEditorProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const addVariable = () => {
    onChange([
      ...variables,
      { name: "", type: "string", required: false, description: "" },
    ]);
    setExpandedIdx(variables.length);
  };

  const updateVariable = (idx: number, updates: Partial<ProcessVariable>) => {
    const updated = [...variables];
    updated[idx] = { ...updated[idx], ...updates };
    onChange(updated);
  };

  const removeVariable = (idx: number) => {
    onChange(variables.filter((_, i) => i !== idx));
    if (expandedIdx === idx) setExpandedIdx(null);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-semibold">Process Variables</Label>
        <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={addVariable}>
          <Plus className="h-3 w-3 mr-1" /> Add
        </Button>
      </div>

      {variables.length === 0 && (
        <p className="text-[10px] text-muted-foreground py-2">
          No process variables defined. Add variables to pass data between nodes.
        </p>
      )}

      <div className="space-y-1">
        {variables.map((v, idx) => (
          <div key={idx} className="rounded-md border bg-muted/30">
            {/* Collapsed row */}
            <div
              className="flex items-center gap-1.5 px-2 py-1.5 cursor-pointer hover:bg-muted/50"
              onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
            >
              <GripVertical className="h-3 w-3 text-muted-foreground shrink-0" />
              <span className="text-xs font-mono flex-1 truncate">
                {v.name || "(unnamed)"}
              </span>
              <span className="text-[10px] text-muted-foreground px-1.5 py-0.5 rounded bg-muted">
                {v.type}
              </span>
              {v.required && (
                <span className="text-[10px] text-red-500">*</span>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5 shrink-0"
                onClick={(e) => { e.stopPropagation(); removeVariable(idx); }}
              >
                <Trash2 className="h-3 w-3 text-muted-foreground" />
              </Button>
            </div>

            {/* Expanded editor */}
            {expandedIdx === idx && (
              <div className="px-2 pb-2 space-y-2 border-t">
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <div>
                    <Label className="text-[10px]" htmlFor="wf-name">Name</Label>
                    <Input
                      id="wf-name"
                      className="h-7 text-xs font-mono"
                      placeholder="variableName"
                      value={v.name}
                      onChange={(e) => updateVariable(idx, { name: e.target.value })}
                    />
                  </div>
                  <div>
                    <Label className="text-[10px]">Type</Label>
                    <Select
                      value={v.type}
                      onValueChange={(t) => updateVariable(idx, { type: t as ProcessVariable["type"] })}
                    >
                      <SelectTrigger className="h-7 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {VAR_TYPES.map((t) => (
                          <SelectItem key={t} value={t} className="text-xs">{t}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div>
                  <Label className="text-[10px]" htmlFor="wf-description">Description</Label>
                  <Input
                    id="wf-description"
                    className="h-7 text-xs"
                    placeholder="What this variable holds"
                    value={v.description || ""}
                    onChange={(e) => updateVariable(idx, { description: e.target.value })}
                  />
                </div>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-1.5 text-[10px]">
                    <input
                      type="checkbox"
                      checked={v.required || false}
                      onChange={(e) => updateVariable(idx, { required: e.target.checked })}
                      className="rounded"
                    />
                    Required
                  </label>
                  <div className="flex-1">
                    <Input
                      className="h-7 text-xs"
                      placeholder="Default value"
                      value={String(v.defaultValue ?? "")}
                      onChange={(e) => updateVariable(idx, { defaultValue: e.target.value })}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
