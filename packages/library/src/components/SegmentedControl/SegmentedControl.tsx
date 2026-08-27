"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SegmentedControlPropsType } from "./SegmentedControl.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SegmentedControlProps extends SegmentedControlPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function SegmentedControl({ name, label, options = [], value, style, onChange }: SegmentedControlProps) {
  const [internal, setInternal] = React.useState(value ?? options[0]?.value);
  const current = value !== undefined ? value : internal;
  const select = (v: string) => { if (value === undefined) setInternal(v); onChange?.(v); };
  return (
    <div className="flex flex-col gap-1" data-segmented-control="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <span className="text-sm font-medium text-foreground">{label}</span>}
      <div role="group" aria-label={label ?? name} className="inline-flex rounded-md border border-border bg-muted p-0.5">
        {options.map((o) => {
          const active = o.value === current;
          return (
            <button key={o.value} type="button" aria-pressed={active} onClick={() => select(o.value)}
              className={`rounded px-3 py-1 text-sm transition-colors ${active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
