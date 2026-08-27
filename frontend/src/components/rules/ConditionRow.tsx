"use client";

import { useMemo } from "react";
import { Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CONDITION_OPERATORS,
  type ConditionNode,
  type ConditionOperator,
} from "@/types/rules";
import {
  operatorsForCategory,
  valueControl,
  type FieldMeta,
} from "@/lib/field-types";

interface ConditionRowProps {
  condition: ConditionNode;
  fields: string[];
  onChange: (updated: ConditionNode) => void;
  onRemove: () => void;
  /** Optional field -> type metadata. When present, the row becomes
   *  type-aware (filtered operators + typed value controls). When absent
   *  (classic Rules tab) the row behaves exactly as before. */
  fieldMeta?: Record<string, FieldMeta>;
}

const UNARY_OPERATORS: ConditionOperator[] = ["is_null", "is_not_null"];

export function ConditionRow({
  condition,
  fields,
  onChange,
  onRemove,
  fieldMeta,
}: ConditionRowProps) {
  const meta = fieldMeta?.[condition.field];
  const isUnary = UNARY_OPERATORS.includes(condition.operator);

  const opLabels = useMemo(
    () => Object.fromEntries(CONDITION_OPERATORS.map((o) => [o.value, o.label])),
    [],
  );

  // Operators: filtered by the field's type when known, else the full set.
  const operatorValues: ConditionOperator[] = meta
    ? operatorsForCategory(meta.category)
    : CONDITION_OPERATORS.map((o) => o.value);

  // Value control: typed when known, else the classic text input (or none for unary).
  const ctrl = meta
    ? valueControl(meta.category, condition.operator)
    : isUnary
      ? "none"
      : "text";

  const changeField = (field: string) => {
    const next = fieldMeta?.[field];
    let operator = condition.operator;
    // If the newly-picked field's type doesn't allow the current operator, pick a valid one.
    if (next && !operatorsForCategory(next.category).includes(operator)) {
      operator = operatorsForCategory(next.category)[0];
    }
    // Reset the value when the field's category changes, or when the
    // (auto-picked) operator is unary (is_null/is_not_null) which takes no value.
    const isUnaryNext = operator === "is_null" || operator === "is_not_null";
    const value = isUnaryNext || meta?.category !== next?.category ? "" : condition.value;
    onChange({ ...condition, field, operator, value });
  };

  return (
    <div className="flex items-center gap-2">
      {/* Field selector — dropdown (with type chips) when fields are known,
          else a typeable input for projects without a generated data model. */}
      {fieldMeta && fields.length === 0 ? (
        // Business Rules editor on a project with no data model → typeable input.
        // (The classic Rules tab passes no fieldMeta, so it keeps the Select even
        // when fields is empty — exact parity with the prior behavior.)
        <Input
          className="h-8 w-[160px] text-xs"
          placeholder="Field..."
          value={condition.field}
          onChange={(e) => onChange({ ...condition, field: e.target.value })}
        />
      ) : (
        <Select value={condition.field || undefined} onValueChange={changeField}>
          <SelectTrigger className="h-8 w-[160px] text-xs">
            <SelectValue placeholder="Field..." />
          </SelectTrigger>
          <SelectContent>
            {fields.map((f) => {
              const fm = fieldMeta?.[f];
              return (
                <SelectItem key={f} value={f} className="text-xs">
                  <span className="flex w-full items-center justify-between gap-2">
                    <span className="truncate">{f}</span>
                    {fm && (
                      <span className="shrink-0 rounded bg-muted px-1 text-[9px] text-muted-foreground">
                        {fm.category}
                      </span>
                    )}
                  </span>
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
      )}

      {/* Operator selector */}
      <Select
        value={condition.operator}
        onValueChange={(v) =>
          onChange({ ...condition, operator: v as ConditionOperator })
        }
      >
        <SelectTrigger className="h-8 w-[130px] text-xs">
          <SelectValue placeholder="Operator..." />
        </SelectTrigger>
        <SelectContent>
          {operatorValues.map((op) => (
            <SelectItem key={op} value={op} className="text-xs">
              {opLabels[op] ?? op}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Value control — typed when the field's type is known. */}
      {ctrl === "enum" ? (
        <Select
          value={condition.value || undefined}
          onValueChange={(v) => onChange({ ...condition, value: v })}
        >
          <SelectTrigger className="h-8 w-[160px] text-xs">
            <SelectValue placeholder="Value..." />
          </SelectTrigger>
          <SelectContent>
            {(meta?.enumValues ?? []).map((v) => (
              <SelectItem key={v} value={v} className="text-xs">
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : ctrl === "boolean" ? (
        <Select
          value={condition.value || undefined}
          onValueChange={(v) => onChange({ ...condition, value: v })}
        >
          <SelectTrigger className="h-8 w-[160px] text-xs">
            <SelectValue placeholder="Value..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true" className="text-xs">true</SelectItem>
            <SelectItem value="false" className="text-xs">false</SelectItem>
          </SelectContent>
        </Select>
      ) : ctrl === "none" ? null : (
        <Input
          type={ctrl === "number" ? "number" : ctrl === "date" ? "date" : "text"}
          className="h-8 w-[160px] text-xs"
          placeholder={ctrl === "list" ? "a, b, c" : "Value..."}
          value={condition.value}
          onChange={(e) => onChange({ ...condition, value: e.target.value })}
        />
      )}

      {/* Remove button */}
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0"
        onClick={onRemove}
      >
        <Trash2 className="h-3 w-3 text-muted-foreground" />
      </Button>
    </div>
  );
}
