"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { TreePropsType, TreeNodeT } from "./Tree.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface TreeProps extends TreePropsType {
  style?: StyleSlotT;
  onSelect?: (value: string) => void;
}

function TreeItem({ node, depth, onSelect }: { node: TreeNodeT; depth: number; onSelect?: (v: string) => void }) {
  const [open, setOpen] = React.useState(false);
  const hasChildren = !!node.children?.length;
  return (
    <li>
      <div className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}>
        {hasChildren ? (
          <button type="button" aria-label={`${open ? "collapse" : "expand"} ${node.label}`} aria-expanded={open}
            onClick={() => setOpen((o) => !o)} className="h-4 w-4 text-muted-foreground">{open ? "▾" : "▸"}</button>
        ) : <span className="inline-block h-4 w-4" />}
        <span className={`py-1 text-sm ${hasChildren ? "font-medium text-foreground" : "cursor-pointer text-foreground hover:text-primary"}`}
          onClick={!hasChildren && node.value !== undefined ? () => onSelect?.(node.value as string) : undefined}>{node.label}</span>
      </div>
      {hasChildren && open && (
        <ul>{node.children!.map((c, i) => <TreeItem key={i} node={c} depth={depth + 1} onSelect={onSelect} />)}</ul>
      )}
    </li>
  );
}

export function Tree({ items = [], style, onSelect }: TreeProps) {
  return (
    <ul className="select-none" data-tree="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {items.map((n, i) => <TreeItem key={i} node={n} depth={0} onSelect={onSelect} />)}
    </ul>
  );
}
