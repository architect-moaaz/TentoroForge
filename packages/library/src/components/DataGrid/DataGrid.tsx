"use client";

import * as React from "react";
import { useDensity } from "../../theme/tokens-context";
import { useVirtualRows } from "./useVirtualRows";
import type { DataGridPropsType } from "./DataGrid.schema";

export interface DataGridProps extends DataGridPropsType {}

const DENSITY_ROW_HEIGHT: Record<string, number> = {
  compact: 32,
  comfortable: 40,
  spacious: 52,
};

/**
 * DataGrid v1 — frozen columns, density-aware row height, row virtualisation
 * (auto-enabled at >100 rows), sortable columns, bulk-select checkbox column,
 * and a row-actions slot (3-dot trigger per row).
 *
 * Future waves: column-resize, group-by, filter-bar slot, expandable rows,
 * persisted saved-views.
 */
export function DataGrid({
  columns = [],
  rows: rowsProp = [],
  rowKey = "id",
  virtualise,
  selectable,
  rowActions,
}: DataGridProps) {
  // `rows` may be a binding string ("{{invoices}}") before the Engine resolves it,
  // and the schema type now reflects that — coerce to an array of records here.
  const rows: Record<string, any>[] = Array.isArray(rowsProp) ? rowsProp : [];
  const density = useDensity();
  const rowHeight = DENSITY_ROW_HEIGHT[density] ?? 40;
  const shouldVirtualise = virtualise ?? rows.length > 100;

  if (columns.length === 0) {
    return (
      <div className="overflow-auto rounded border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
        No columns defined.
      </div>
    );
  }

  const scrollRef = React.useRef<HTMLDivElement>(null);
  const virtualiser = useVirtualRows(scrollRef, rows.length, rowHeight);

  const [sortBy, setSortBy] = React.useState<{
    key: string;
    dir: "asc" | "desc";
  } | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());

  const sortedRows = React.useMemo(() => {
    if (!sortBy) return rows;
    return [...rows].sort((a, b) => {
      const av = a[sortBy.key];
      const bv = b[sortBy.key];
      if (av === bv) return 0;
      const cmp = av > bv ? 1 : -1;
      return sortBy.dir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortBy]);

  const toggleSort = (key: string) => {
    setSortBy((prev) =>
      prev?.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" },
    );
  };

  const toggleSelect = (id: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const renderRow = (row: Record<string, unknown>, index: number) => {
    const rowId = String(row[rowKey] ?? index);
    return (
      <tr
        key={rowId}
        className="border-b border-border hover:bg-muted/30 transition-colors"
        style={{ height: rowHeight }}
      >
        {selectable && (
          <td className="w-10 px-2 align-middle">
            <input
              type="checkbox"
              aria-label={`Select row ${rowId}`}
              checked={selected.has(rowId)}
              onChange={(e) => toggleSelect(rowId, e.target.checked)}
              className="cursor-pointer"
            />
          </td>
        )}
        {columns.map((col) => {
          const alignClass =
            col.align === "right"
              ? "text-right"
              : col.align === "center"
                ? "text-center"
                : "";
          const frozenClass = col.frozen
            ? "sticky left-0 bg-card z-[1]"
            : "";
          return (
            <td
              key={col.key}
              className={`px-3 align-middle text-sm ${alignClass} ${frozenClass}`}
              style={{ width: col.width }}
            >
              {row[col.key] != null ? String(row[col.key]) : "—"}
            </td>
          );
        })}
        {rowActions && rowActions.length > 0 && (
          <td className="w-10 px-2 align-middle text-center">
            <button
              type="button"
              aria-label="Row actions"
              className="text-muted-foreground hover:text-foreground text-lg leading-none"
              data-row-actions={rowId}
            >
              &#8943;
            </button>
          </td>
        )}
      </tr>
    );
  };

  return (
    <div
      ref={scrollRef}
      className="overflow-auto rounded border border-border bg-card"
      style={{ maxHeight: shouldVirtualise ? 480 : undefined }}
    >
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-muted/40 backdrop-blur">
          <tr>
            {selectable && <th className="w-10" />}
            {columns.map((col) => {
              const frozenClass = col.frozen
                ? "sticky left-0 bg-muted/40 z-10"
                : "";
              return (
                <th
                  key={col.key}
                  className={`px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground ${frozenClass}`}
                  style={{ width: col.width }}
                >
                  {col.sortable ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(col.key)}
                      className="inline-flex items-center gap-1 hover:text-foreground"
                    >
                      {col.label}
                      {sortBy?.key === col.key && (
                        <span aria-hidden="true">
                          {sortBy.dir === "asc" ? " ↑" : " ↓"}
                        </span>
                      )}
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              );
            })}
            {rowActions && rowActions.length > 0 && <th className="w-10" />}
          </tr>
        </thead>
        <tbody>
          {shouldVirtualise ? (
            <>
              {/* Spacer row that holds the total virtual height */}
              <tr
                aria-hidden="true"
                style={{ height: virtualiser.getTotalSize() }}
              />
              {virtualiser.getVirtualItems().map((vi) => (
                <React.Fragment key={vi.key}>
                  {renderRow(sortedRows[vi.index], vi.index)}
                </React.Fragment>
              ))}
            </>
          ) : (
            sortedRows.map((row, i) => renderRow(row, i))
          )}
        </tbody>
      </table>
    </div>
  );
}
