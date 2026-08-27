"use client";
import * as React from "react";
import { ActionPicker } from "./ActionPicker";
import { BindingControl } from "./BindingControl";

const labelCls = "flex flex-col gap-1 text-sm";
const labelText = "text-xs uppercase tracking-wide text-muted-foreground";

export interface ControlProps {
  label: string;
  value: any;
  onChange: (v: any) => void;
  options?: readonly string[];
  placeholder?: string;
}

export function TextControl({ label, value, onChange, placeholder }: ControlProps) {
  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <input
        type="text"
        className="border rounded px-2 py-1 text-sm bg-background"
        value={typeof value === "string" ? value : value ?? ""}
        placeholder={placeholder ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function TextareaControl({ label, value, onChange }: ControlProps) {
  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <textarea
        rows={3}
        className="border rounded px-2 py-1 text-sm bg-background font-mono"
        value={typeof value === "string" ? value : JSON.stringify(value ?? "", null, 2)}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function NumberControl({ label, value, onChange }: ControlProps) {
  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <input
        type="number"
        className="border rounded px-2 py-1 text-sm bg-background"
        value={typeof value === "number" ? value : 0}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

export function SelectControl({ label, value, onChange, options }: ControlProps) {
  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <select
        className="border rounded px-2 py-1 text-sm bg-background"
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
      >
        {(options ?? []).map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </label>
  );
}

export function ToggleControl({ label, value, onChange }: ControlProps) {
  return (
    <label className="flex items-center justify-between text-sm">
      <span className={labelText}>{label}</span>
      <input
        type="checkbox"
        checked={!!value}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4"
      />
    </label>
  );
}

export function ColorControl({ label, value, onChange }: ControlProps) {
  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <input
        type="color"
        className="border rounded h-8 w-full bg-background"
        value={typeof value === "string" && value.startsWith("#") ? value : "#000000"}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function ActionControl({ label, value, onChange }: ControlProps) {
  // V1: action is JSON-edited as text. Picker UI is future work.
  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <textarea
        rows={3}
        className="border rounded px-2 py-1 text-xs bg-background font-mono"
        value={value === undefined || value === null ? "" : JSON.stringify(value, null, 2)}
        onChange={(e) => {
          const raw = e.target.value;
          try { onChange(JSON.parse(raw)); }
          catch { onChange(raw); }
        }}
        placeholder='{"action": "navigate", "trigger": "..."}'
      />
    </label>
  );
}

export const CONTROL_BY_TYPE = {
  text: TextControl,
  textarea: TextareaControl,
  number: NumberControl,
  select: SelectControl,
  toggle: ToggleControl,
  color: ColorControl,
  actionPicker: ActionPicker,
  spacing: TextControl,      // fallback — proper spacing picker is future work
  binding: BindingControl,   // data-aware binding editor (page dataSources + scopes)
  iconPicker: TextControl,   // fallback — proper icon picker is future work
} as const;
