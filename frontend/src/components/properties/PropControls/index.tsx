"use client";
import { ActionPicker } from "./ActionPicker";
import { BindingControl } from "./BindingControl";
import { ImageControl } from "./ImageControl";
import { RawJsonEditor } from "./RawJsonEditor";
import { RowsControl } from "./RowsControl";
import type { ImageShape } from "@forge/registry";

const labelCls = "flex flex-col gap-1 text-sm";
const labelText = "text-xs uppercase tracking-wide text-muted-foreground";

export interface ControlProps {
  label: string;
  value: any;
  onChange: (v: any) => void;
  options?: readonly string[];
  placeholder?: string;
  // Context every control receives and most ignore. ImageControl needs the
  // owning node to say how big the slot renders, the registry's shape hint to
  // know whether the prop is a bare url string or an object wrapping one, and
  // the project id to upload against. Passing them to every control keeps
  // PropertiesPanel's single <Control /> call site generic instead of
  // special-casing one control type in the render loop.
  imageShape?: ImageShape;
  nodeType?: string;
  nodeProps?: Record<string, unknown>;
  projectId?: string | null;
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

/**
 * Editor for structured props no picker can express — the four AppShell
 * composition slots (each a schema sub-tree) and every `type:"array"` prop.
 *
 * WHY it exists: those props were wired to ActionPicker, whose ONLY output is
 * an action object like {action:"navigate",trigger:""}. AppShell renders them
 * in React child position, so picking any action threw "Objects are not valid
 * as a React child" and blanked the entire page (docs/editor-audit/
 * containment.md finding #1) — the panel's only control for the prop was the
 * one value guaranteed to break it.
 *
 * WHY it delegates to RowsControl for arrays instead of waiting for the registry
 * to say `control:"rows"`: the registry emits `control:"json"` today, and a
 * better control that only activates once a *different* package is rebuilt is
 * exactly the failure this phase is fixing — `Select.options` was converted to
 * `type:"array"` a session ago and the panel never showed it (input-components-2
 * D1). Delegating on the VALUE's shape means the row editor is live the moment
 * this file lands, and stays correct if the registry later switches to "rows".
 * Objects (the AppShell slots) are unaffected: they are not arrays.
 *
 * The raw editor keeps its commit-on-blur / parse-or-refuse contract — see
 * RawJsonEditor.
 */
export function JsonControl({ label, value, onChange }: ControlProps) {
  if (Array.isArray(value)) {
    return <RowsControl label={label} value={value} onChange={onChange} />;
  }
  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <RawJsonEditor label={label} value={value} onChange={onChange} />
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
  image: ImageControl,       // drag-drop / browse upload + URL text, with dimensions
  json: JsonControl,         // structured props: rows for arrays, raw JSON otherwise
  rows: RowsControl,         // repeating {value,label} rows (option lists, chips)
} as const;

export { ImageControl, RowsControl, RawJsonEditor };
