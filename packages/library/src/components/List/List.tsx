"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ListPropsType } from "./List.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { SCROLL_X } from "../../style/scroll";
import { applyRowCap } from "../../style/rowCap";
import { asListItem } from "../../style/rowShape";
import { useNavigator } from "@tentoroforge/renderer";

export interface ListProps extends ListPropsType {
  /** Max rows to render; set by the dashboard composer. */
  limit?: number;
  style?: StyleSlotT;
  onItemClick?: (index: number) => void;
}

export function List({ items = [], divided = true, style, onItemClick, limit, itemHref }: ListProps) {
  const nav = useNavigator();
  // See ActivityFeed: the composer caps a list that shares a grid row.
  const raw = applyRowCap(Array.isArray(items) ? items : [], limit) as unknown[];
  // A data row (a note, an attachment, a case) is shaped into an item by its
  // own columns; with `itemHref` the item opens its record, as a table row does.
  const rows = raw.map(asListItem);
  const hrefs = raw.map((r) => itemHref && r && typeof r === "object"
    ? itemHref.replace(/\{\{?\s*(\w+)\s*\}\}?/g, (_m, k) => String((r as Record<string, unknown>)[k] ?? ""))
    : undefined);
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
          onClick={hrefs[i] ? () => nav.push(hrefs[i] as string) : onItemClick ? () => onItemClick(i) : undefined}
          {...(hrefs[i] ? { role: "link", tabIndex: 0, "data-href": hrefs[i] } : {})}
          className={`flex items-center gap-3 px-4 py-3 ${onItemClick || hrefs[i] ? "cursor-pointer hover:bg-muted/50" : ""}`}
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
