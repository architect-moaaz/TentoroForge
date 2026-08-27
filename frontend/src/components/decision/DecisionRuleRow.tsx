"use client";

import { GripVertical, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DecisionCellEditor } from "./DecisionCellEditor";
import type { DecisionTableDefinition, DecisionTableRule } from "@/types/decision";
import type { AppModel } from "@/types/app-model";

interface DecisionRuleRowProps {
  rule: DecisionTableRule;
  index: number;
  table: DecisionTableDefinition;
  onChange: (rule: DecisionTableRule) => void;
  onDelete: () => void;
  readOnly?: boolean;
  highlighted?: "dead" | "overlap" | null;
  appModel?: AppModel | null;
}

export function DecisionRuleRow({
  rule,
  index,
  table,
  onChange,
  onDelete,
  readOnly,
  highlighted,
  appModel,
}: DecisionRuleRowProps) {
  const updateInputEntry = (colIndex: number, value: string) => {
    const inputEntries = [...rule.inputEntries];
    inputEntries[colIndex] = value;
    onChange({ ...rule, inputEntries });
  };

  const updateOutputEntry = (colIndex: number, value: string) => {
    const outputEntries = [...rule.outputEntries];
    outputEntries[colIndex] = value;
    onChange({ ...rule, outputEntries });
  };

  const highlightClass =
    highlighted === "dead"
      ? "bg-red-50"
      : highlighted === "overlap"
        ? "bg-amber-50"
        : "";

  return (
    <tr className={`group ${highlightClass}`}>
      {/* Row number + drag handle */}
      <td className="border px-1 py-0 text-center text-[10px] text-muted-foreground w-8">
        <div className="flex items-center justify-center gap-0.5">
          {!readOnly && (
            <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50 cursor-grab" />
          )}
          <span>{index + 1}</span>
        </div>
      </td>

      {/* Input cells */}
      {table.inputs.map((input, colIndex) => (
        <td key={input.id} className="border p-0">
          {readOnly ? (
            <div className="px-2 py-1.5 text-xs font-mono">
              {rule.inputEntries[colIndex] || "-"}
            </div>
          ) : (
            <DecisionCellEditor
              value={rule.inputEntries[colIndex] || ""}
              onChange={(v) => updateInputEntry(colIndex, v)}
              columnType="input"
              columnName={input.name}
              appModel={appModel}
            />
          )}
        </td>
      ))}

      {/* Output cells */}
      {table.outputs.map((output, colIndex) => (
        <td key={output.id} className="border p-0">
          {readOnly ? (
            <div className="px-2 py-1.5 text-xs font-mono">
              {rule.outputEntries[colIndex] || ""}
            </div>
          ) : (
            <DecisionCellEditor
              value={rule.outputEntries[colIndex] || ""}
              onChange={(v) => updateOutputEntry(colIndex, v)}
              columnType="output"
              columnName={output.name}
              appModel={appModel}
            />
          )}
        </td>
      ))}

      {/* Annotation */}
      <td className="border p-0">
        {readOnly ? (
          <div className="px-2 py-1.5 text-xs text-muted-foreground truncate max-w-[120px]">
            {rule.annotation || ""}
          </div>
        ) : (
          <input
            className="h-8 w-full bg-transparent px-2 text-xs text-muted-foreground outline-none placeholder:text-muted-foreground/50"
            value={rule.annotation || ""}
            onChange={(e) => onChange({ ...rule, annotation: e.target.value })}
            placeholder="Note..."
          />
        )}
      </td>

      {/* Delete button */}
      {!readOnly && (
        <td className="border-y px-1 py-0 w-6">
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 opacity-0 group-hover:opacity-100"
            onClick={onDelete}
          >
            <X className="h-3 w-3 text-muted-foreground" />
          </Button>
        </td>
      )}
    </tr>
  );
}
