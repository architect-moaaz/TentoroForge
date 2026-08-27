"use client";

import { Label } from "@/components/ui/label";
import { ConditionBuilder } from "@/components/rules/ConditionBuilder";
import { ExpressionEditor } from "./ExpressionEditor";
import type { ConditionExpression } from "@/types/rules";
import type { VariableSchema } from "@/lib/feel-lite";

interface ConditionModeToggleProps {
  mode: "visual" | "expression";
  onModeChange: (mode: "visual" | "expression") => void;
  // Visual mode props
  conditionTree: ConditionExpression | null;
  onConditionTreeChange: (tree: ConditionExpression | null) => void;
  fields: string[];
  // Expression mode props
  expression: string;
  onExpressionChange: (expr: string) => void;
  variables?: VariableSchema[];
}

export function ConditionModeToggle({
  mode,
  onModeChange,
  conditionTree,
  onConditionTreeChange,
  fields,
  expression,
  onExpressionChange,
  variables,
}: ConditionModeToggleProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1 rounded-md border p-0.5">
        <button
          type="button"
          className={`flex-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
            mode === "visual"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => onModeChange("visual")}
        >
          Visual
        </button>
        <button
          type="button"
          className={`flex-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
            mode === "expression"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => onModeChange("expression")}
        >
          Expression
        </button>
      </div>

      {mode === "visual" ? (
        <ConditionBuilder
          value={conditionTree}
          onChange={onConditionTreeChange}
          fields={fields}
        />
      ) : (
        <div className="space-y-1">
          <Label className="text-xs">FEEL-lite Expression</Label>
          <ExpressionEditor
            value={expression}
            onChange={onExpressionChange}
            variables={variables}
            height={60}
          />
          <p className="text-[10px] text-muted-foreground">
            True branch exits right. False branch exits bottom.
          </p>
        </div>
      )}
    </div>
  );
}
