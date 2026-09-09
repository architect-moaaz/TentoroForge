"use client";

/**
 * KeyValueMapper — the value control for object-typed inputs.
 *
 * Renders one row per key with a fixed KEY input on the left and a
 * VALUE control on the right (variable dropdown or literal typed value).
 * Emits the mapping as a plain `Record<string, unknown>` — variables
 * are stored verbatim as `{{path}}` references so the runtime's
 * walk-and-interpolate resolves them at exec time.
 *
 * Used inside InputMappingSection for object-type inputs (e.g.
 * `http_call.body`, `http_call.headers`, `generate_document.record`)
 * as the replacement for a raw JSON textarea. Also mounted directly
 * as an editor for trigger inputMapping.
 *
 * Spec: docs/superpowers/specs/2026-07-22-workflow-node-contracts.md
 */

import { useState } from "react";
import { Plus, Trash2, Variable, Type } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { WorkflowVariable } from "./workflowVariables";

interface KeyValueMapperProps {
  value: Record<string, unknown> | undefined;
  variables: WorkflowVariable[];
  onChange: (next: Record<string, unknown>) => void;
  keyPlaceholder?: string;
  addLabel?: string;
  /**
   * Presets for the KEY column. Renders as a datalist. Handy when the
   * caller knows likely keys (e.g. `["Content-Type","Authorization"]`
   * for `http_call.headers`) but doesn't want to lock them in.
   */
  keySuggestions?: readonly string[];
}

export function KeyValueMapper({
  value,
  variables,
  onChange,
  keyPlaceholder = "key",
  addLabel = "Add",
  keySuggestions,
}: KeyValueMapperProps) {
  const entries = Object.entries(value ?? {});

  const addRow = () => {
    const v = value ?? {};
    // Keys are unique, so a second blank "" row would overwrite the first —
    // clicking Add looked like a no-op. If a blank row already exists, give the
    // new one a distinct placeholder key the user then renames.
    let key = "";
    if (Object.prototype.hasOwnProperty.call(v, "")) {
      let i = 1;
      while (Object.prototype.hasOwnProperty.call(v, `key${i}`)) i += 1;
      key = `key${i}`;
    }
    onChange({ ...v, [key]: "" });
  };

  const updateKey = (oldKey: string, newKey: string) => {
    const next: Record<string, unknown> = {};
    for (const [k, v] of entries) {
      next[k === oldKey ? newKey : k] = v;
    }
    onChange(next);
  };

  const updateValue = (key: string, v: unknown) => {
    onChange({ ...(value ?? {}), [key]: v });
  };

  const removeRow = (key: string) => {
    const next = { ...(value ?? {}) };
    delete next[key];
    onChange(next);
  };

  const listId = keySuggestions && keySuggestions.length > 0
    ? `kv-${Math.random().toString(36).slice(2, 8)}`
    : undefined;

  return (
    <div className="space-y-1.5">
      {listId && (
        <datalist id={listId}>
          {keySuggestions!.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
      {entries.length === 0 && (
        <p className="text-[10px] text-muted-foreground">
          No entries yet — add one below.
        </p>
      )}
      {entries.map(([key, val], idx) => (
        <Row
          key={idx}
          k={key}
          v={val}
          variables={variables}
          listId={listId}
          keyPlaceholder={keyPlaceholder}
          onKeyChange={(nk) => updateKey(key, nk)}
          onValueChange={(nv) => updateValue(key, nv)}
          onRemove={() => removeRow(key)}
        />
      ))}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-6 px-1.5 text-[10px] text-muted-foreground"
        onClick={addRow}
      >
        <Plus className="mr-1 h-3 w-3" /> {addLabel}
      </Button>
    </div>
  );
}

type RowSource = "variable" | "literal";

function inferRowSource(v: unknown): RowSource {
  if (typeof v === "string" && /^\{\{.+\}\}$/.test(v.trim())) return "variable";
  return "literal";
}

function Row({
  k,
  v,
  variables,
  listId,
  keyPlaceholder,
  onKeyChange,
  onValueChange,
  onRemove,
}: {
  k: string;
  v: unknown;
  variables: WorkflowVariable[];
  listId?: string;
  keyPlaceholder: string;
  onKeyChange: (s: string) => void;
  onValueChange: (v: unknown) => void;
  onRemove: () => void;
}) {
  // The row's source used to be inferred purely from the value: a `{{…}}`
  // string was "variable", anything else "literal". But switching TO variable
  // cleared the value to "", which then inferred back to "literal" — so the
  // variable dropdown never appeared and the toggle was a silent no-op. We
  // keep an explicit source in local state; a concrete `{{binding}}` value
  // still wins (it is authoritatively a variable), otherwise the chosen state
  // decides, so an empty value can legitimately be in variable mode.
  const [sourceState, setSourceState] = useState<RowSource>(() => inferRowSource(v));
  const source: RowSource = inferRowSource(v) === "variable" ? "variable" : sourceState;
  // For variable source we store `{{path}}`; the Select value is just the path.
  const variablePath =
    source === "variable" && typeof v === "string"
      ? v.trim().replace(/^\{\{\s*/, "").replace(/\s*\}\}$/, "")
      : "";
  const literalText = source === "literal" && typeof v !== "object" ? String(v ?? "") : "";

  const setSource = (s: RowSource) => {
    if (s === source) return;
    setSourceState(s);
    // Clear the value so the new control starts empty; a variable is set when
    // the user picks one, a literal when they type. The local source state
    // keeps the variable dropdown visible in the meantime.
    onValueChange("");
  };

  const groups = new Map<string, WorkflowVariable[]>();
  for (const wv of variables) {
    const g = groups.get(wv.sourceLabel) ?? [];
    g.push(wv);
    groups.set(wv.sourceLabel, g);
  }

  return (
    <div className="flex items-center gap-1">
      <Input
        className="h-7 flex-1 text-[11px] font-mono"
        placeholder={keyPlaceholder}
        list={listId}
        value={k}
        onChange={(e) => onKeyChange(e.target.value)}
      />
      <Select value={source} onValueChange={(s) => setSource(s as RowSource)}>
        <SelectTrigger className="h-7 w-[92px] text-[10px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="variable" className="text-[11px]">
            <span className="flex items-center gap-1">
              <Variable className="h-3 w-3" /> variable
            </span>
          </SelectItem>
          <SelectItem value="literal" className="text-[11px]">
            <span className="flex items-center gap-1">
              <Type className="h-3 w-3" /> literal
            </span>
          </SelectItem>
        </SelectContent>
      </Select>
      {source === "variable" ? (
        <Select
          value={variablePath}
          onValueChange={(p) => onValueChange(`{{${p}}}`)}
        >
          <SelectTrigger className="h-7 flex-1 text-[11px] font-mono">
            <SelectValue placeholder="Select variable…" />
          </SelectTrigger>
          <SelectContent>
            {Array.from(groups.entries()).map(([label, vars]) => (
              <SelectGroup key={label}>
                <SelectLabel className="text-[10px] uppercase text-muted-foreground">
                  {label}
                </SelectLabel>
                {vars.map((wv) => (
                  <SelectItem key={wv.path} value={wv.path} className="text-[11px] font-mono">
                    {wv.path}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
            {variables.length === 0 && (
              <SelectItem value="__none" disabled className="text-[11px]">
                No variables available
              </SelectItem>
            )}
          </SelectContent>
        </Select>
      ) : (
        <Input
          className="h-7 flex-1 text-[11px]"
          value={literalText}
          onChange={(e) => onValueChange(e.target.value)}
        />
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0"
        onClick={onRemove}
        title="Remove"
      >
        <Trash2 className="h-3 w-3 text-muted-foreground" />
      </Button>
    </div>
  );
}
