"use client";

import { useCallback } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConditionRow } from "./ConditionRow";
import type {
  ConditionExpression,
  ConditionGroup,
  ConditionNode,
} from "@/types/rules";
import type { FieldMeta } from "@/lib/field-types";

interface ConditionBuilderProps {
  value: ConditionExpression | null;
  onChange: (value: ConditionExpression | null) => void;
  fields: string[];
  /** Optional field -> type metadata for type-aware authoring (forwarded to rows). */
  fieldMeta?: Record<string, FieldMeta>;
}

let nextId = 1;
function genId() {
  return `cond_${nextId++}`;
}

function newCondition(): ConditionNode {
  return { id: genId(), field: "", operator: "equals", value: "" };
}

function newGroup(logic: "AND" | "OR" = "AND"): ConditionGroup {
  return { id: genId(), logic, conditions: [newCondition()] };
}

function isGroup(expr: ConditionExpression): expr is ConditionGroup {
  return "logic" in expr;
}

export function ConditionBuilder({
  value,
  onChange,
  fields,
  fieldMeta,
}: ConditionBuilderProps) {
  // Ensure we always work with a group at the top level
  const group: ConditionGroup = value && isGroup(value)
    ? value
    : value
      ? { id: genId(), logic: "AND", conditions: [value] }
      : newGroup();

  const updateCondition = useCallback(
    (index: number, updated: ConditionNode) => {
      const conditions = [...group.conditions];
      conditions[index] = updated;
      onChange({ ...group, conditions });
    },
    [group, onChange],
  );

  const removeCondition = useCallback(
    (index: number) => {
      const conditions = group.conditions.filter((_, i) => i !== index);
      if (conditions.length === 0) {
        onChange(null);
      } else {
        onChange({ ...group, conditions });
      }
    },
    [group, onChange],
  );

  const addCondition = useCallback(() => {
    onChange({ ...group, conditions: [...group.conditions, newCondition()] });
  }, [group, onChange]);

  const addNestedGroup = useCallback(() => {
    onChange({ ...group, conditions: [...group.conditions, newGroup()] });
  }, [group, onChange]);

  const setLogic = useCallback(
    (logic: "AND" | "OR") => {
      onChange({ ...group, logic });
    },
    [group, onChange],
  );

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Label className="text-xs font-medium">Condition</Label>
        <Select
          value={group.logic}
          onValueChange={(v) => setLogic(v as "AND" | "OR")}
        >
          <SelectTrigger className="h-7 w-[80px] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="AND" className="text-xs">AND</SelectItem>
            <SelectItem value="OR" className="text-xs">OR</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2 rounded-md border bg-muted/20 p-3">
        {group.conditions.map((cond, i) =>
          isGroup(cond) ? (
            <div key={cond.id} className="ml-4 border-l-2 border-muted pl-3">
              <ConditionBuilder
                value={cond}
                onChange={(updated) => {
                  const conditions = [...group.conditions];
                  if (updated) {
                    conditions[i] = updated;
                  } else {
                    conditions.splice(i, 1);
                  }
                  onChange(
                    conditions.length > 0
                      ? { ...group, conditions }
                      : null,
                  );
                }}
                fields={fields}
                fieldMeta={fieldMeta}
              />
            </div>
          ) : (
            <ConditionRow
              key={cond.id}
              condition={cond}
              fields={fields}
              onChange={(updated) => updateCondition(i, updated)}
              onRemove={() => removeCondition(i)}
              fieldMeta={fieldMeta}
            />
          ),
        )}

        <div className="flex gap-2 pt-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={addCondition}
          >
            <Plus className="mr-1 h-3 w-3" />
            Condition
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={addNestedGroup}
          >
            <Plus className="mr-1 h-3 w-3" />
            Group
          </Button>
        </div>
      </div>
    </div>
  );
}
