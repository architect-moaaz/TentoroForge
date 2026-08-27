"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DecisionTableEditor } from "@/components/decision/DecisionTableEditor";
import type { DecisionTableDefinition, DecisionTableInput } from "@/types/decision";
import type { AppModel, ColumnModel } from "@/types/app-model";
import { fieldCategory } from "@/lib/field-types";

let nextTableId = 1;

/** A blank DMN-style decision table to seed a new decision_table rule. */
export function emptyDecisionTable(): DecisionTableDefinition {
  const n = nextTableId++;
  return {
    id: `dt_${n}`,
    name: "Decision Table",
    hitPolicy: "U",
    inputs: [{ id: `in_${n}_1`, name: "input1", type: "any" }],
    outputs: [{ id: `out_${n}_1`, name: "output1", type: "any" }],
    rules: [{ id: `r_${n}_1`, inputEntries: ["-"], outputEntries: [""] }],
  };
}

/** Map a data-model field category to a decision-table column type. */
function toColumnType(cat: ReturnType<typeof fieldCategory>): DecisionTableInput["type"] {
  switch (cat) {
    case "number": return "number";
    case "boolean": return "boolean";
    case "date": return "date";
    case "string":
    case "enum": return "string";
    default: return "any";
  }
}

interface DecisionTableModeProps {
  name: string;
  onNameChange: (name: string) => void;
  table: DecisionTableDefinition;
  onTableChange: (table: DecisionTableDefinition) => void;
  /** Data model — enables FEEL cell autocomplete + field-bound columns. */
  appModel: AppModel | null;
  models: string[];
  getFields: (model: string | null | undefined) => ColumnModel[];
  enumValuesForType: (type: string | undefined) => string[] | null;
}

export function DecisionTableMode({
  name,
  onNameChange,
  table,
  onTableChange,
  appModel,
  models,
  getFields,
  enumValuesForType,
}: DecisionTableModeProps) {
  const [boundModel, setBoundModel] = useState<string | null>(null);
  // Fall back to the first model so the binder works on first render even if
  // the data model loaded after mount (boundModel still null).
  const effectiveModel = boundModel ?? models[0] ?? null;
  const fields = getFields(effectiveModel);

  const addColumnFromField = (fieldName: string, kind: "input" | "output") => {
    const col = fields.find((c) => c.name === fieldName);
    if (!col) return;
    const cat = fieldCategory(col.type, !!enumValuesForType(col.type));
    const type = toColumnType(cat);
    if (kind === "input") {
      const input: DecisionTableInput = {
        id: `in_${crypto.randomUUID()}`,
        name: col.name,
        type,
        variableBinding: col.name,
      };
      onTableChange({
        ...table,
        inputs: [...table.inputs, input],
        rules: table.rules.map((r) => ({ ...r, inputEntries: [...r.inputEntries, "-"] })),
      });
    } else {
      onTableChange({
        ...table,
        outputs: [...table.outputs, { id: `out_${crypto.randomUUID()}`, name: col.name, type }],
        rules: table.rules.map((r) => ({ ...r, outputEntries: [...r.outputEntries, ""] })),
      });
    }
  };

  return (
    <div className="space-y-4">
      <div className="max-w-sm space-y-1">
        <Label className="text-xs">Rule name</Label>
        <Input
          className="h-8 text-sm"
          placeholder="e.g. discount-tier"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
        />
      </div>

      {models.length > 0 && (
        <div className="flex flex-wrap items-end gap-2 rounded-md border bg-muted/10 p-2.5">
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Bind to model</Label>
            <Select value={effectiveModel ?? undefined} onValueChange={setBoundModel}>
              <SelectTrigger className="h-7 w-[160px] text-xs">
                <SelectValue placeholder="Model" />
              </SelectTrigger>
              <SelectContent>
                {models.map((m) => (
                  <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <AddFromField label="Add input from field" fields={fields} onPick={(f) => addColumnFromField(f, "input")} />
          <AddFromField label="Add output from field" fields={fields} onPick={(f) => addColumnFromField(f, "output")} />
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Each row is a rule: input cells are FEEL conditions ( <code>-</code> = any,{" "}
        <code>&gt; 100</code>, <code>[1..10]</code>, <code>&quot;gold&quot;</code> ), output cells
        are the result. The hit policy decides what happens when multiple rows match.
      </p>

      <DecisionTableEditor table={table} onChange={onTableChange} appModel={appModel} />
    </div>
  );
}

function AddFromField({
  label,
  fields,
  onPick,
}: {
  label: string;
  fields: ColumnModel[];
  onPick: (field: string) => void;
}) {
  // This Select is a command menu, not a stateful field. Radix only fires
  // onValueChange when the value CHANGES, so remount via a changing key after
  // each pick — otherwise picking the same field twice silently does nothing.
  const [n, setN] = useState(0);
  if (fields.length === 0) return null;
  return (
    <div className="space-y-1">
      <Label className="text-[11px] text-muted-foreground">{label}</Label>
      <Select
        key={n}
        value={undefined}
        onValueChange={(f) => {
          onPick(f);
          setN((x) => x + 1);
        }}
      >
        <SelectTrigger className="h-7 w-[180px] text-xs">
          <span className="flex items-center gap-1 text-muted-foreground">
            <Plus className="h-3 w-3" /> field…
          </span>
        </SelectTrigger>
        <SelectContent>
          {fields.map((c) => (
            <SelectItem key={c.name} value={c.name} className="text-xs">
              <span className="flex w-full items-center justify-between gap-2">
                <span className="truncate">{c.name}</span>
                <span className="shrink-0 rounded bg-muted px-1 text-[9px] text-muted-foreground">
                  {c.type}
                </span>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
