"use client";
import { useMemo, useState, type ReactNode } from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useRuntimeArmed } from "@tentoroforge/renderer";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import type { ColumnDef } from "./Table.schema";

type SortDir = "asc" | "desc" | null;

type Props = {
  columns: ColumnDef[];
  caption?: string;
  /**
   * The rows to sort and render.
   *
   * `unknown` for the same reason `TableProps.rows` is: in an authored page
   * this is a Mustache binding string (`"{{items}}"`) that the renderer
   * interpolates to an array of records *before* this component is called, so
   * both forms reach it and only the resolved one is renderable. Anything that
   * is not an array means "no data supplied", which is a different state from
   * "an empty list" only in the sense that neither has rows — both take the
   * empty branch, and neither is a crash.
   */
  rows?: unknown;
  /** Headline for the empty state. Falls back to the component's own copy. */
  emptyText?: string;
  children?: ReactNode;
  onSort?: (key: string, dir: "asc" | "desc") => void;
  style?: StyleSlotT;
  /** Schema-authored utility classes. Declared and dropped before — a producer
   *  writing `props.className` on this node had it silently discarded, unlike
   *  every sibling in the family. */
  className?: string;
};

/**
 * A SORTABLE TABLE THAT HAD NOTHING TO SORT.
 *
 * This component took `{columns, caption, children, onSort, style}` and built
 * its `<tbody>` from `children` alone — while `tableSortableEntry.slots` is
 * `{ type: "leaf" }`, so the editor could never give it children. Every route
 * to a row was closed: no `rows` prop existed in any layer to expose, and the
 * children route was shut by the registry. A dropped TableSortable measured
 * 960x90 with `ths = ["Name","Status"]` and a `<tbody>` holding **zero** rows,
 * permanently, and — unlike Table, which at least *has* an (unreachable) empty
 * state — there was no empty branch in the source at all, so it did not even
 * say so. The audit rated it critical and routed it here because, unlike
 * Table's identical void, this one could not be fixed from the registry: you
 * cannot expose a prop the component does not have.
 *
 * `rows` is the fix, and it is deliberately the same shape Table's is — a
 * binding over one of the project's collections, resolved by the renderer —
 * rather than a seeded literal array. A seeded array would freeze design-time
 * sample data into a shipped app, which is the trap this codebase keeps
 * re-learning: a seed that is read as a command.
 *
 * The `children` path is kept and takes precedence when no `rows` are supplied,
 * because hand-authored pages in the wild already put `<tr>`s inside this
 * component and must not start rendering an empty state instead. That is the
 * same `dataMode` split Table uses, for the same reason.
 *
 * Sorting now sorts something. It was previously a state change over zero rows:
 * `aria-sort` flipped, the header grew an arrow, and nothing moved.
 */
export function TableSortable({
  columns,
  caption,
  rows,
  emptyText,
  children,
  onSort,
  style,
  className,
}: Props) {
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

  const records = Array.isArray(rows)
    ? (rows as Record<string, unknown>[])
    : null;
  // Same split as Table: explicit rows put the component in data mode; a
  // hand-authored subtree keeps the legacy children mode. `!children` rather
  // than `children == null` so an empty fragment does not silently win over
  // supplied data.
  const dataMode = !!records && !children;

  const sorted = useMemo(() => {
    if (!records) return [];
    if (!sortKey || !sortDir) return records;
    const dir = sortDir === "asc" ? 1 : -1;
    // Copy before sorting: `Array.prototype.sort` mutates, and `records` is the
    // caller's array — in data mode it is the resolved binding, which other
    // nodes on the page may be reading at the same time.
    return [...records].sort((a, b) => {
      const av = a?.[sortKey];
      const bv = b?.[sortKey];
      // Blanks sink in BOTH directions, so the direction multiplier must not
      // reach them: "no value" is not the smallest value, it is absent, and a
      // user reversing the sort does not expect the gaps to lead.
      const aBlank = av == null || av === "";
      const bBlank = bv == null || bv === "";
      if (aBlank && bBlank) return 0;
      if (aBlank) return 1;
      if (bBlank) return -1;
      return compareCells(av, bv) * dir;
    });
  }, [records, sortKey, sortDir]);

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
      <tbody>
        {!dataMode && children}
        {dataMode && sorted.length === 0 && (
          // `data-forge-empty` marks this as a DELIBERATE empty state, the same
          // marker Table uses: without it "nothing to show, and we said so" and
          // "the widget silently drew nothing" are identical in the DOM, which
          // is exactly the ambiguity that let this component ship a void.
          <tr data-forge-empty="table-sortable">
            <td
              colSpan={Math.max(1, columns.length)}
              style={{ padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted-foreground, hsl(0 0% 45%))", fontSize: "0.875rem" }}
            >
              {emptyText || "Nothing here yet"}
            </td>
          </tr>
        )}
        {dataMode && sorted.map((row, rowIdx) => (
          <tr key={String(row?.id ?? rowIdx)}>
            {columns.map((col) => (
              <td
                key={col.key}
                style={{ padding: "0.5rem 0.75rem", textAlign: col.align ?? "left" }}
              >
                {formatCell(row?.[col.key])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Sort comparison that does not lie about types.
 *
 * A plain `String(a) < String(b)` sorts "10" before "9", which reads as a
 * broken sort rather than as data the component does not understand. Numbers
 * and booleans compare as themselves, numeric strings compare numerically, and
 * everything else falls back to a locale compare with `numeric: true` so mixed
 * text like "Item 2" / "Item 10" still orders the way a reader expects.
 *
 * Blanks are handled by the caller, before the direction multiplier, so they
 * sink in both directions.
 */
function compareCells(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);

  const aNum = typeof a === "string" ? Number(a) : NaN;
  const bNum = typeof b === "string" ? Number(b) : NaN;
  if (!Number.isNaN(aNum) && !Number.isNaN(bNum) && a !== "" && b !== "") return aNum - bNum;

  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** Cells render as text; an object would otherwise reach React as a child and throw. */
function formatCell(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
