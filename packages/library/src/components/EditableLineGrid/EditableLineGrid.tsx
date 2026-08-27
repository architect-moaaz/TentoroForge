"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import type { EditableLineGridPropsType } from "./EditableLineGrid.schema";
import { resolveIcon } from "../../icons";

type Row = Record<string, unknown>;
type Column = EditableLineGridPropsType["columns"][number];

export interface EditableLineGridProps extends EditableLineGridPropsType {
  style?: StyleSlotT;
  /** Controlled-mode change handler. Receives the next rows array. */
  onRowsChange?: (rows: Row[]) => void;
  /** Lookup submit handler — called when the user presses Enter in the
   *  lookup field. Receives the typed query. Hosts typically resolve the
   *  query to a Row and call onRowsChange to append it. */
  onLookup?: (query: string) => void;
}

const TH_CLS = "px-3 py-2 text-xs font-medium text-muted-foreground border-b border-border";
const TD_CLS = "px-2 py-1.5 border-b border-border align-middle";
const INPUT_CLS =
  "w-full h-8 px-2 text-sm bg-transparent border-0 rounded " +
  "focus:outline-none focus:ring-2 focus:ring-ring focus:bg-background " +
  "disabled:cursor-not-allowed disabled:text-muted-foreground";
const SELECT_CLS = INPUT_CLS + " cursor-pointer";

const ALIGN_TEXT: Record<"left" | "center" | "right", string> = {
  left: "text-left", center: "text-center", right: "text-right",
};

function _coerceNumber(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function _computeAutoTotals(rows: Row[]): { subtotal: number } {
  // Detect price*qty pattern across rows. Use any of: price/qty, unitPrice/quantity,
  // amount, total — first match wins per row.
  let subtotal = 0;
  for (const r of rows) {
    if (r.total != null)        { subtotal += _coerceNumber(r.total); continue; }
    if (r.amount != null)       { subtotal += _coerceNumber(r.amount); continue; }
    const price = _coerceNumber(r.price ?? r.unitPrice ?? 0);
    const qty   = _coerceNumber(r.qty ?? r.quantity ?? 1);
    const disc  = _coerceNumber(r.discount ?? 0); // absolute, not percent
    subtotal += Math.max(0, price * qty - disc);
  }
  return { subtotal };
}

function _formatCurrency(n: number, currency: string): string {
  const fixed = n.toFixed(2);
  return currency ? `${fixed} ${currency}` : fixed;
}

export function EditableLineGrid({
  columns,
  rows,
  rowKey = "id",
  lookupPlaceholder,
  showLookup = false,
  totals,
  removable = false,
  emptyMessage = "No line items.",
  className,
  style,
  onRowsChange,
  onLookup,
}: EditableLineGridProps) {
  const [lookupQuery, setLookupQuery] = React.useState("");
  const SearchIcon = resolveIcon("search");
  const XIcon = resolveIcon("x");

  // Resolve totals — explicit values trump auto-computed.
  const resolved = React.useMemo(() => {
    if (!totals) return null;
    let { subtotal, tax, total, taxLabel, taxRate, currency } = totals;
    if (totals.auto) {
      const auto = _computeAutoTotals(rows);
      subtotal = subtotal ?? auto.subtotal;
    }
    subtotal = subtotal ?? 0;
    if (tax == null && typeof taxRate === "number") {
      tax = subtotal * taxRate;
    }
    tax = tax ?? 0;
    total = total ?? (subtotal + tax);
    return { subtotal, tax, total, taxLabel: taxLabel ?? "VAT", currency: currency ?? "" };
  }, [totals, rows]);

  const updateCell = (rowIdx: number, key: string, value: unknown) => {
    if (!onRowsChange) return;
    const next = rows.map((r, i) => (i === rowIdx ? { ...r, [key]: value } : r));
    onRowsChange(next);
  };

  const removeRow = (rowIdx: number) => {
    if (!onRowsChange) return;
    onRowsChange(rows.filter((_, i) => i !== rowIdx));
  };

  const submitLookup = () => {
    const q = lookupQuery.trim();
    if (!q || !onLookup) return;
    onLookup(q);
    setLookupQuery("");
  };

  const renderCell = (col: Column, row: Row, rowIdx: number) => {
    const value = row[col.key];
    const align = col.align ?? "left";
    const onChangeText = (v: string) => updateCell(rowIdx, col.key, v);
    const onChangeNum = (v: string) => {
      const n = v === "" ? "" : parseFloat(v);
      updateCell(rowIdx, col.key, n);
    };
    switch (col.type) {
      case "readonly":
        return (
          <span className={`block px-2 py-1.5 text-sm ${ALIGN_TEXT[align]}`}>
            {value == null ? "" : String(value)}
          </span>
        );
      case "number":
        return (
          <input
            type="number"
            className={`${INPUT_CLS} ${ALIGN_TEXT[align]} tabular-nums`}
            value={value == null ? "" : String(value)}
            placeholder={col.placeholder}
            onChange={(e) => onChangeNum(e.target.value)}
          />
        );
      case "currency":
        return (
          <input
            type="number"
            step="0.01"
            className={`${INPUT_CLS} ${ALIGN_TEXT[align]} tabular-nums`}
            value={value == null ? "" : String(value)}
            placeholder={col.placeholder}
            onChange={(e) => onChangeNum(e.target.value)}
          />
        );
      case "select":
        return (
          <select
            className={`${SELECT_CLS} ${ALIGN_TEXT[align]}`}
            value={value == null ? "" : String(value)}
            onChange={(e) => onChangeText(e.target.value)}
          >
            <option value="" disabled>{col.placeholder ?? "Select…"}</option>
            {(col.options ?? []).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        );
      case "text":
      default:
        return (
          <input
            type="text"
            className={`${INPUT_CLS} ${ALIGN_TEXT[align]}`}
            value={value == null ? "" : String(value)}
            placeholder={col.placeholder}
            onChange={(e) => onChangeText(e.target.value)}
          />
        );
    }
  };

  return (
    <div
      className={["w-full", className].filter(Boolean).join(" ")}
      style={resolveStyle(style)}
      data-component="EditableLineGrid"
      {...useMotion(style?.motion)}
    >
      {showLookup && (
        <div className="relative mb-3">
          {SearchIcon && (
            <SearchIcon
              size={16}
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
          )}
          <input
            type="text"
            value={lookupQuery}
            onChange={(e) => setLookupQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submitLookup(); } }}
            placeholder={lookupPlaceholder ?? "Add item — enter name, code, or barcode"}
            className="w-full h-10 pl-9 pr-3 text-sm rounded-md border border-input bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-line-grid-lookup=""
          />
        </div>
      )}

      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full text-sm border-collapse">
          <thead className="bg-muted/50">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`${TH_CLS} ${ALIGN_TEXT[col.align ?? "left"]}`}
                  style={col.width ? { width: col.width } : undefined}
                >
                  {col.label}
                </th>
              ))}
              {removable && <th className={TH_CLS} style={{ width: 32 }} aria-label="Remove" />}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length + (removable ? 1 : 0)}
                    className="px-3 py-8 text-center text-sm text-muted-foreground">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row, rowIdx) => {
                const key = (row[rowKey] as React.Key | undefined) ?? rowIdx;
                return (
                  <tr key={key} data-row-key={String(key)}>
                    {columns.map((col) => (
                      <td key={col.key}
                          className={`${TD_CLS} ${ALIGN_TEXT[col.align ?? "left"]}`}
                          style={col.width ? { width: col.width } : undefined}>
                        {renderCell(col, row, rowIdx)}
                      </td>
                    ))}
                    {removable && (
                      <td className={`${TD_CLS} text-center`}>
                        <button
                          type="button"
                          aria-label="Remove row"
                          className="inline-flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                          onClick={() => removeRow(rowIdx)}
                        >
                          {XIcon ? <XIcon size={14} aria-hidden="true" /> : "×"}
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {resolved && (
        <dl className="mt-4 ml-auto w-full max-w-xs space-y-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Subtotal</dt>
            <dd className="tabular-nums">{_formatCurrency(resolved.subtotal, resolved.currency)}</dd>
          </div>
          {(resolved.tax !== 0 || totals?.taxRate != null) && (
            <div className="flex justify-between">
              <dt className="text-muted-foreground">{resolved.taxLabel}</dt>
              <dd className="tabular-nums">{_formatCurrency(resolved.tax, resolved.currency)}</dd>
            </div>
          )}
          <div className="flex justify-between border-t border-border pt-1 font-semibold">
            <dt>Total</dt>
            <dd className="tabular-nums">{_formatCurrency(resolved.total, resolved.currency)}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
