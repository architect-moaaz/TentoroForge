"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { TransferPropsType } from "./Transfer.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface TransferProps extends TransferPropsType {
  style?: StyleSlotT;
  onChange?: (selected: string[]) => void;
}

export function Transfer({ name, options = [], selected, titles = ["Available", "Selected"], style, onChange }: TransferProps) {
  const [sel, setSel] = React.useState<string[]>(selected ?? []);
  const [focus, setFocus] = React.useState<string | null>(null);
  const inSel = (v: string) => sel.includes(v);
  const commit = (next: string[]) => { setSel(next); onChange?.(next); };
  const move = (toSelected: boolean) => {
    if (focus === null) return;
    commit(toSelected ? [...sel, focus] : sel.filter((v) => v !== focus));
    setFocus(null);
  };
  const Panel = ({ title, items, testid }: { title: string; items: typeof options; testid: string }) => (
    <div className="flex-1 rounded-md border border-border" data-testid={testid}>
      <div className="border-b border-border px-3 py-1.5 text-xs font-medium text-muted-foreground">{title}</div>
      <ul className="max-h-48 overflow-auto p-1">
        {items.map((o) => (
          <li key={o.value} onClick={() => setFocus(o.value)}
            className={`cursor-pointer rounded px-2 py-1 text-sm ${focus === o.value ? "bg-primary/10 text-primary" : "hover:bg-muted/50"}`}>{o.label}</li>
        ))}
      </ul>
    </div>
  );
  return (
    <div className="flex items-center gap-2" data-transfer="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <Panel title={titles[0] ?? "Available"} items={options.filter((o) => !inSel(o.value))} testid="transfer-available" />
      <div className="flex flex-col gap-1">
        <button type="button" aria-label="move right" onClick={() => move(true)} className="rounded border border-border px-2 py-1 text-sm hover:bg-muted">›</button>
        <button type="button" aria-label="move left" onClick={() => move(false)} className="rounded border border-border px-2 py-1 text-sm hover:bg-muted">‹</button>
      </div>
      <Panel title={titles[1] ?? "Selected"} items={options.filter((o) => inSel(o.value))} testid="transfer-selected" />
      {/* The two panels are <li>s — nothing named, so FormData saw nothing.
          Serialise the selection as JSON under `name` (same convention as
          KeyValueInput, which is what makes a jsonb value submittable). */}
      {name && <input type="hidden" name={name} value={JSON.stringify(sel)} readOnly />}
    </div>
  );
}
