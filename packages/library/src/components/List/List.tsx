"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ListPropsType } from "./List.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { SCROLL_X } from "../../style/scroll";
import { applyRowCap } from "../../style/rowCap";
import { asListItem } from "../../style/rowShape";

export interface ListProps extends ListPropsType {
  /** Max rows to render; set by the dashboard composer. */
  limit?: number;
  style?: StyleSlotT;
  onItemClick?: (index: number) => void;
}

export function List({ items = [], divided = true, style, onItemClick, limit }: ListProps) {
  // See ActivityFeed: the composer caps a list that shares a grid row.
  // A data row (a note, an attachment) is shaped into an item by its own columns.
  const rows = applyRowCap((Array.isArray(items) ? items : []).map(asListItem), limit);
  return (
    <ul
      className={`rounded-lg border border-border ${SCROLL_X} ${divided ? "divide-y divide-border" : ""}`}
      data-list=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {rows.map((it, i) => (
        <li
          key={i}
          onClick={onItemClick ? () => onItemClick(i) : undefined}
          className={`flex items-center gap-3 px-4 py-3 ${onItemClick ? "cursor-pointer hover:bg-muted/50" : ""}`}
        >
          <div className="flex min-w-0 flex-col break-words">
            <span className="text-sm font-medium text-foreground">{it.title}</span>
            {it.subtitle && (
              <span className="text-xs text-muted-foreground">{it.subtitle}</span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
