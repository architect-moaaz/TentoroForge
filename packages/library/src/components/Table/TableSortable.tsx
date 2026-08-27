"use client";
import { useState, type ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import type { ColumnDef } from "./Table.schema";

type SortDir = "asc" | "desc" | null;

type Props = {
  columns: ColumnDef[];
  caption?: string;
  children?: ReactNode;
  onSort?: (key: string, dir: "asc" | "desc") => void;
  style?: StyleSlotT;
};

export function TableSortable({ columns, caption, children, onSort, style }: Props) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);

  function handleSort(key: string) {
    let nextDir: SortDir;
    if (sortKey === key) {
      nextDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      nextDir = "asc";
    }
    setSortKey(key);
    setSortDir(nextDir);
    if (onSort) onSort(key, nextDir);
  }

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", ...resolveStyle(style) }} {...useMotion(style?.motion)}>
      {caption && <caption>{caption}</caption>}
      <thead>
        <tr>
          {columns.map((col) => {
            const isSorted = sortKey === col.key;
            const ariaSort = isSorted
              ? (sortDir === "asc" ? "ascending" : "descending")
              : undefined;
            return (
              <th
                key={col.key}
                scope="col"
                aria-sort={ariaSort}
                onClick={() => handleSort(col.key)}
                style={{
                  width: col.width,
                  textAlign: "left",
                  padding: "0.5rem 0.75rem",
                  cursor: "pointer",
                  userSelect: "none",
                }}
              >
                {col.label}
                {isSorted && <span aria-hidden="true">{sortDir === "asc" ? " ↑" : " ↓"}</span>}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}
