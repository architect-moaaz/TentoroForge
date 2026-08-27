"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { KeyValueInputPropsType } from "./KeyValueInput.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface KeyValueInputProps extends KeyValueInputPropsType {
  style?: StyleSlotT;
  value?: Record<string, unknown>;
  onChange?: (value: Record<string, unknown>) => void;
}

type Row = { k: string; v: string };

function coerce(v: string, t?: string): unknown {
  if (t === "number") {
    if (v.trim() === "") return null;
    const n = Number(v);
    return Number.isNaN(n) ? v : n;
  }
  if (t === "boolean") return ["true", "1", "yes", "on"].includes(v.trim().toLowerCase());
  return v;
}

function toRows(obj?: Record<string, unknown>): Row[] {
  if (!obj || typeof obj !== "object") return [];
  return Object.entries(obj).map(([k, v]) => ({ k, v: v == null ? "" : String(v) }));
}

function toObject(rows: Row[], valueType?: string): Record<string, unknown> {
  const o: Record<string, unknown> = {};
  for (const r of rows) {
    const key = r.k.trim();
    if (key) o[key] = coerce(r.v, valueType);
  }
  return o;
}

/**
 * Editable string→value map for a jsonb / config column. Self-manages its rows
 * and serialises them to a hidden `<input name>` holding JSON — so a container
 * (FormData) Form submits the object as a JSON string, which the runtime data
 * engine parses back into an object for the jsonb column. When a parent passes
 * `onChange` it also reports the live object (controlled use in the editor).
 */
export function KeyValueInput({
  name, label, description, valueType, disabled, style, value, onChange,
}: KeyValueInputProps) {
  const [rows, setRows] = React.useState<Row[]>(() => toRows(value));
  const obj = toObject(rows, valueType);

  const commit = (next: Row[]) => {
    setRows(next);
    onChange?.(toObject(next, valueType));
  };
  const update = (i: number, patch: Partial<Row>) =>
    commit(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = () => commit([...rows, { k: "", v: "" }]);
  const remove = (i: number) => commit(rows.filter((_, j) => j !== i));

  return (
    <div className="flex flex-col gap-2" data-keyvalue-input="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}</label>}
      {description && <p className="text-xs text-muted-foreground">{description}</p>}
      {/* Hidden control so a container-mode (FormData) Form picks up the value. */}
      <input type="hidden" name={name} value={JSON.stringify(obj)} readOnly />
      <div className="flex flex-col gap-1.5">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <input
              aria-label="key" placeholder="key" disabled={disabled} value={r.k}
              onChange={(e) => update(i, { k: e.target.value })}
              className="min-w-0 flex-1 rounded-md border border-input bg-transparent px-2 py-1 text-sm focus-visible:outline-none" />
            <span className="text-muted-foreground">:</span>
            <input
              aria-label="value" placeholder="value" disabled={disabled} value={r.v}
              onChange={(e) => update(i, { v: e.target.value })}
              className="min-w-0 flex-1 rounded-md border border-input bg-transparent px-2 py-1 text-sm focus-visible:outline-none" />
            <button type="button" aria-label="remove row" disabled={disabled} onClick={() => remove(i)}
              className="px-2 py-1 text-muted-foreground hover:text-foreground disabled:opacity-50">×</button>
          </div>
        ))}
        {rows.length === 0 && <p className="text-xs text-muted-foreground">No entries yet.</p>}
      </div>
      <button type="button" disabled={disabled} onClick={add}
        className="self-start rounded-md border border-input px-2 py-1 text-sm text-foreground hover:bg-muted disabled:opacity-50">
        + Add entry
      </button>
    </div>
  );
}
