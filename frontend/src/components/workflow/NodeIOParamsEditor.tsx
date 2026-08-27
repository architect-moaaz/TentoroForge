"use client";

/**
 * NodeIOParamsEditor — edits inputParams and outputParams for a workflow node.
 *
 * Shows two sections:
 * - Input Params: which process variables this node reads
 * - Output Params: which process variables this node writes
 */

import { Plus, Trash2, ArrowDown, ArrowUp } from "lucide-react";
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
import type { NodeParam, ProcessVariable } from "@/types/workflow";

interface NodeIOParamsEditorProps {
  inputParams: NodeParam[];
  outputParams: NodeParam[];
  processVariables: ProcessVariable[];
  onUpdateInputs: (params: NodeParam[]) => void;
  onUpdateOutputs: (params: NodeParam[]) => void;
}

const PARAM_TYPES = ["string", "number", "boolean", "object", "array", "date"] as const;

function ParamList({
  label,
  icon,
  params,
  processVariables,
  onChange,
  mappingField,
}: {
  label: string;
  icon: React.ReactNode;
  params: NodeParam[];
  processVariables: ProcessVariable[];
  onChange: (params: NodeParam[]) => void;
  mappingField: "source" | "target";
}) {
  const addParam = () => {
    onChange([...params, { name: "", type: "string" }]);
  };

  const updateParam = (idx: number, updates: Partial<NodeParam>) => {
    const updated = [...params];
    updated[idx] = { ...updated[idx], ...updates };
    onChange(updated);
  };

  const removeParam = (idx: number) => {
    onChange(params.filter((_, i) => i !== idx));
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Label className="text-[10px] font-semibold flex items-center gap-1">
          {icon} {label}
        </Label>
        <Button variant="ghost" size="sm" className="h-5 px-1.5 text-[10px]" onClick={addParam}>
          <Plus className="h-2.5 w-2.5 mr-0.5" /> Add
        </Button>
      </div>

      {params.length === 0 && (
        <p className="text-[10px] text-muted-foreground">No {label.toLowerCase()} defined.</p>
      )}

      {params.map((p, idx) => (
        <div key={idx} className="flex items-center gap-1">
          <Input
            className="h-6 text-[10px] font-mono flex-1"
            placeholder="paramName"
            value={p.name}
            onChange={(e) => updateParam(idx, { name: e.target.value })}
          />
          <Select
            value={p[mappingField] || ""}
            onValueChange={(v) => updateParam(idx, { [mappingField]: v })}
          >
            <SelectTrigger className="h-6 text-[10px] w-[100px]">
              <SelectValue placeholder="variable" />
            </SelectTrigger>
            <SelectContent>
              {processVariables.map((pv) => (
                <SelectItem key={pv.name} value={pv.name} className="text-[10px]">
                  {pv.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0"
            onClick={() => removeParam(idx)}
          >
            <Trash2 className="h-2.5 w-2.5 text-muted-foreground" />
          </Button>
        </div>
      ))}
    </div>
  );
}

export function NodeIOParamsEditor({
  inputParams,
  outputParams,
  processVariables,
  onUpdateInputs,
  onUpdateOutputs,
}: NodeIOParamsEditorProps) {
  return (
    <div className="space-y-3">
      <ParamList
        label="Input Params"
        icon={<ArrowDown className="h-3 w-3 text-blue-500" />}
        params={inputParams}
        processVariables={processVariables}
        onChange={onUpdateInputs}
        mappingField="source"
      />
      <ParamList
        label="Output Params"
        icon={<ArrowUp className="h-3 w-3 text-green-500" />}
        params={outputParams}
        processVariables={processVariables}
        onChange={onUpdateOutputs}
        mappingField="target"
      />
    </div>
  );
}
