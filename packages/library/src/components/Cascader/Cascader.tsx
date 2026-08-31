"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CascaderPropsType, CascaderOptionT } from "./Cascader.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface CascaderProps extends CascaderPropsType {
  style?: StyleSlotT;
  onChange?: (path: string[]) => void;
}

export function Cascader({ options = [], style, onChange }: CascaderProps) {
  // path of selected values, one per revealed column
  const [path, setPath] = React.useState<string[]>([]);

  // build the list of columns to render based on the current path
  const columns: CascaderOptionT[][] = [options];
  let level: CascaderOptionT[] = options;
  for (let i = 0; i < path.length; i++) {
    const chosen = level.find((o) => o.value === path[i]);
    if (chosen?.children?.length) { columns.push(chosen.children); level = chosen.children; }
    else break;
  }

  const pick = (colIndex: number, opt: CascaderOptionT) => {
    const next = [...path.slice(0, colIndex), opt.value];
    setPath(next);
    if (!opt.children?.length) onChange?.(next); // leaf
  };

  return (
    <div className="inline-flex rounded-md border border-border" data-cascader="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {columns.map((col, ci) => (
        <ul key={ci} className="min-w-[140px] border-e border-border last:border-e-0 p-1">
          {col.map((o) => {
            const active = path[ci] === o.value;
            return (
              <li key={o.value} onClick={() => pick(ci, o)}
                className={`flex cursor-pointer items-center justify-between rounded px-2 py-1 text-sm ${active ? "bg-primary/10 text-primary" : "hover:bg-muted/50"}`}>
                {o.label}{o.children?.length ? <span className="text-muted-foreground">›</span> : null}
              </li>
            );
          })}
        </ul>
      ))}
    </div>
  );
}
