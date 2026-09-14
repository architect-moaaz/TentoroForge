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
 * Future waves: column-resize, group-by, filter-bar slot, persisted saved-views.
 *
 * `expandable` — "Allow rows to expand for detail content." The registry has
 * advertised it with a live toggle all along while this file listed it as a
 * future wave, so the control saved a value that changed nothing. The detail
 * panel shows the row fields the columns do NOT already display (and every
 * field when the columns cover them all), which is the only detail content
 * available without a per-row slot in the schema.
 */
export function DataGrid({
  columns = [],
  rows: rowsProp = [],
  rowKey = "id",
  virtualise,
  selectable,
  expandable,
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
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const hasRowActions = Boolean(rowActions && rowActions.length > 0);
  const detailSpan =
    columns.length + (selectable ? 1 : 0) + (expandable ? 1 : 0) + (hasRowActions ? 1 : 0);

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

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
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
    const isExpanded = expanded.has(rowId);
    const shown = new Set(columns.map((c) => c.key));
    const detailEntries = Object.entries(row).filter(([k]) => !shown.has(k));
    const details = detailEntries.length > 0 ? detailEntries : Object.entries(row);
    return (
      <React.Fragment key={rowId}>
      <tr
        className="border-b border-border hover:bg-muted/30 transition-colors"
        style={{ height: rowHeight }}
      >
        {expandable && (
          <td className="w-8 px-1 align-middle">
            <button
              type="button"
              aria-expanded={isExpanded}
              aria-label={isExpanded ? `Collapse row ${rowId}` : `Expand row ${rowId}`}
              onClick={() => toggleExpand(rowId)}
              data-row-expand={rowId}
              className="text-muted-foreground hover:text-foreground text-xs leading-none"
            >
              <span aria-hidden="true">{isExpanded ? "▾" : "▸"}</span>
            </button>
          </td>
        )}
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
              ? "text-end"
              : col.align === "center"
                ? "text-center"
                : "";
          const frozenClass = col.frozen
            ? "sticky start-0 bg-card z-[1]"
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
      {expandable && isExpanded && (
        <tr className="border-b border-border bg-muted/20" data-row-detail={rowId}>
          <td colSpan={detailSpan} className="px-6 py-3 text-sm">
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
              {details.map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">{k}</dt>
                  <dd className="text-sm">{v != null ? String(v) : "—"}</dd>
                </React.Fragment>
              ))}
            </dl>
          </td>
        </tr>
      )}
      </React.Fragment>
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
            {expandable && <th className="w-8" />}
            {selectable && <th className="w-10" />}
            {columns.map((col) => {
              const frozenClass = col.frozen
                ? "sticky start-0 bg-muted/40 z-10"
                : "";
              return (
                <th
                  key={col.key}
                  className={`px-3 py-2 text-start text-xs font-semibold uppercase tracking-wide text-muted-foreground ${frozenClass}`}
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
            {hasRowActions && <th className="w-10" />}
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
