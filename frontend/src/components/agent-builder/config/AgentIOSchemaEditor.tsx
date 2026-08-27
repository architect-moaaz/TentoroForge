"use client";

/**
 * AgentIOSchemaEditor — declare the agent's inputs (what a caller must supply)
 * and outputs (what the agent returns). Stored on AgentDefinition.config so
 * every persisted agent carries a machine-readable I/O contract that
 * downstream consumers (workflow `agent_call` nodes, chat pages, other agents
 * that hold this one as a tool) can bind against.
 *
 * Compact — sits at the top of the AgentBuilderPanel, collapsible.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AgentIOField } from "@/types/agent-builder";

interface Props {
  inputs: AgentIOField[];
  outputs: AgentIOField[];
  onChange: (v: { inputs: AgentIOField[]; outputs: AgentIOField[] }) => void;
}

const FIELD_TYPES: AgentIOField["type"][] = [
  "string", "number", "boolean", "object", "array", "date", "uuid",
];

function FieldRow({
  field, onChange, onRemove,
}: {
  field: AgentIOField;
  onChange: (f: AgentIOField) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid grid-cols-[1fr_84px_44px_auto] items-center gap-1">
      <Input
        className="h-7 text-[11px]"
        placeholder="name"
        value={field.name}
        onChange={(e) => onChange({ ...field, name: e.target.value })}
      />
      <Select
        value={field.type}
        onValueChange={(v) => onChange({ ...field, type: v as AgentIOField["type"] })}
      >
        <SelectTrigger className="h-7 text-[11px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FIELD_TYPES.map((t) => (
            <SelectItem key={t} value={t} className="text-[11px]">
              {t}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="flex items-center justify-center" title="Required?">
        <Switch
          checked={field.required}
          onCheckedChange={(v) => onChange({ ...field, required: v === true })}
        />
      </div>
      <Button
        type="button" variant="ghost" size="icon" className="h-6 w-6"
        onClick={onRemove}
      >
        <Trash2 className="h-3 w-3 text-muted-foreground" />
      </Button>
      <Input
        className="col-span-4 h-6 text-[10px]"
        placeholder="Description (helps the caller understand what to send / what to expect)"
        value={field.description || ""}
        onChange={(e) => onChange({ ...field, description: e.target.value })}
      />
    </div>
  );
}

function FieldGroup({
  label, fields, onChange,
}: {
  label: string;
  fields: AgentIOField[];
  onChange: (v: AgentIOField[]) => void;
}) {
  const add = () => onChange([...fields, { name: "", type: "string", required: false }]);
  const updateAt = (i: number, f: AgentIOField) => {
    const next = [...fields];
    next[i] = f;
    onChange(next);
  };
  const removeAt = (i: number) => onChange(fields.filter((_, idx) => idx !== i));

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {label}
        </Label>
        <Button
          type="button" variant="ghost" size="sm"
          className="h-6 px-2 text-[10px]"
          onClick={add}
        >
          <Plus className="mr-1 h-3 w-3" />
          Add field
        </Button>
      </div>
      {fields.length === 0 ? (
        <p className="text-[10px] text-muted-foreground italic px-2 py-1">
          No fields declared — the agent takes/returns free-form text.
        </p>
      ) : (
        <div className="space-y-2">
          {fields.map((f, i) => (
            <FieldRow
              key={i} field={f}
              onChange={(v) => updateAt(i, v)}
              onRemove={() => removeAt(i)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function AgentIOSchemaEditor({ inputs, outputs, onChange }: Props) {
  const [open, setOpen] = useState<boolean>(false);

  return (
    <div className="border-b bg-muted/20">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 px-3 py-2 text-xs font-medium hover:bg-muted/40"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <span>Agent I/O schema</span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {inputs.length} in · {outputs.length} out
        </span>
      </button>
      {open && (
        <div className="space-y-4 border-t bg-white px-3 py-3">
          <FieldGroup
            label="Inputs (a caller must supply)"
            fields={inputs}
            onChange={(v) => onChange({ inputs: v, outputs })}
          />
          <FieldGroup
            label="Outputs (the agent returns)"
            fields={outputs}
            onChange={(v) => onChange({ inputs, outputs: v })}
          />
        </div>
      )}
    </div>
  );
}
