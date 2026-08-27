"use client";
import * as React from "react";
import { useEditorStore } from "@/lib/editor-store";

/**
 * Data-aware key picker for chart axis / series keys (xKey, dataKey, …).
 *
 * A chart's xKey must match a field in the resolved data — a series resolves to
 * [{label, value}], so xKey should be "label" and the series dataKey "value".
 * Left as free text it silently drifts to the default "date" (a field that
 * doesn't exist), so the chart renders blank. This reads the node's bound `data`
 * source and offers its actual keys as a dropdown, with a Custom… escape hatch.
 */
export interface DataKeyControlProps {
  label: string;
  value: any;
  onChange: (v: any) => void;
  pageId?: string;
  /** The node being edited — used to read its `data` binding. */
  node?: any;
}

const CUSTOM = "__custom__";
const labelCls = "flex flex-col gap-1 text-sm";
const labelText = "text-xs uppercase tracking-wide text-muted-foreground";

/** Pull the source name out of a `{{name}}` / `source:name` / `name` binding. */
function sourceNameFromBinding(v: unknown): string | null {
  if (typeof v !== "string" || !v) return null;
  const m = v.match(/^\{\{\s*([^}]+?)\s*\}\}$/);
  let expr = m ? m[1] : v;
  if (expr.startsWith("source:")) expr = expr.slice(7);
  // Head of a dotted / indexed path: "src.field" | "src[0].x" → "src".
  return expr.split(/[.[]/)[0] || null;
}

export function DataKeyControl({ label, value, onChange, pageId, node }: DataKeyControlProps) {
  const artifacts = useEditorStore((s) => s.artifacts);
  const currentPageId = useEditorStore((s) => s.currentPageId);
  const pid = pageId ?? currentPageId;

  const keys = React.useMemo<string[]>(() => {
    const out: string[] = [];
    const srcName = sourceNameFromBinding(node?.props?.data);
    const sources: any[] =
      (pid && (artifacts as any)?.pageSchemas?.[pid]?.dataSources) || [];
    const src = sources.find((s) => s?.name === srcName);
    if (src) {
      const op = src.op;
      if (op === "series") out.push("label", "value");
      else if (op === "aggregate" || op === "stats") out.push(...Object.keys(src.metrics || {}));
      else out.push("label", "value", "name"); // list/detail: generic chart keys
    }
    // Always offer the series defaults so a just-bound chart is one click away.
    for (const k of ["label", "value"]) if (!out.includes(k)) out.push(k);
    return out;
  }, [artifacts, pid, node]);

  const val = typeof value === "string" ? value : "";
  const known = keys.includes(val);
  const [customMode, setCustomMode] = React.useState(!known && !!val);

  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <select
        className="border rounded px-2 py-1 text-sm bg-background"
        value={customMode ? CUSTOM : (known ? val : "")}
        onChange={(e) => {
          const v = e.target.value;
          if (v === CUSTOM) { setCustomMode(true); return; }
          setCustomMode(false);
          onChange(v);
        }}
        title="Field key from the bound data source"
      >
        <option value="">Key…</option>
        {keys.map((k) => <option key={k} value={k}>{k}</option>)}
        <option value={CUSTOM}>Custom…</option>
      </select>
      {customMode && (
        <input
          type="text"
          className="border rounded px-2 py-1 text-xs bg-background font-mono"
          value={val}
          placeholder="custom field key"
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </label>
  );
}
