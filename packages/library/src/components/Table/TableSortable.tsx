"use client";
import { useState, type ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useRuntimeArmed } from "@tentoroforge/renderer";
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
  /** Schema-authored utility classes. Declared and dropped before — a producer
   *  writing `props.className` on this node had it silently discarded, unlike
   *  every sibling in the family. */
  className?: string;
};

export function TableSortable({ columns, caption, children, onSort, style, className }: Props) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  // THE HEADER IS THE ONLY VISIBLE PART OF THIS COMPONENT, AND CLICKING IT ON
  // THE CANVAS SORTED INSTEAD OF SELECTING.
  //
  // Measured: clicking "Name" in the editor flipped `aria-sort` to
  // `"ascending"` and the header text to "Name ↓" — the author's click on the
  // one thing they can see mutated component state, over zero rows, instead of
  // doing an editor thing. Same rule as every other runtime handler: it belongs
  // to the running app, not to the surface the app is being drawn on.
  const sortArmed = useRuntimeArmed();

  function handleSort(key: string) {
    if (!sortArmed) return;
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
    <table className={className} style={{ width: "100%", borderCollapse: "collapse", ...resolveStyle(style) }} {...useMotion(style?.motion)}>
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
                  // The affordance follows the behaviour: a header that will not
                  // sort must not advertise that it will.
                  cursor: sortArmed ? "pointer" : "default",
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
