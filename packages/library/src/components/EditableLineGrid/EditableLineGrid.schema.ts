import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * EditableLineGrid — a line-item editor (PO line items, invoice rows, order
 * builder) where every cell is in-place editable, an optional SKU-lookup
 * input lives at the top, and a totals footer rolls up Subtotal / VAT /
 * Total from the rows.
 *
 * Read-only? Use Table or DataGrid. This component is specifically for the
 * "spreadsheet-inside-a-card" interaction pattern.
 */

const ColumnCellType = z.enum([
  "text",      // plain text input
  "number",    // numeric input (qty, integer fields)
  "currency",  // formatted currency input (price, discount)
  "select",    // dropdown of fixed options
  "readonly",  // displayed but not editable (computed values, IDs)
]);

const LineColumn = z.object({
  key:      z.string(),                          // matches a key in each row
  label:    z.string(),                          // header text
  type:     ColumnCellType.default("text"),
  options:  z.array(z.object({                   // for type:"select"
    label: z.string(),
    value: z.string(),
  })).optional(),
  align:    z.enum(["left", "center", "right"]).default("left"),
  width:    z.string().optional(),               // CSS width, e.g. "120px" or "20%"
  placeholder: z.string().optional(),
});

export const EditableLineGridProps = z.object({
  /** Column definitions — left-to-right order. */
  columns: z.array(LineColumn),
  /** Row data — each row is an object keyed by column.key. */
  rows: z.array(z.record(z.unknown())).default([]),
  /** Unique-id key on each row. Used to track edits / deletions stably. */
  rowKey: z.string().default("id"),
  /** Lookup input above the grid — Figma calls it
   *  `Add item — enter name, code, barcode or item number`. */
  lookupPlaceholder: z.string().optional(),
  showLookup: z.boolean().default(false),
  /** Totals footer block. When `auto: true` and rows have numeric
   *  `price` * `qty` fields, the component computes subtotal/tax/total
   *  on the fly. Explicit values always win when provided. */
  totals: z.object({
    auto:      z.boolean().default(false),
    subtotal:  z.number().optional(),
    taxLabel:  z.string().default("VAT"),
    taxRate:   z.number().min(0).max(1).optional(),  // 0.05 = 5%
    tax:       z.number().optional(),
    total:     z.number().optional(),
    currency:  z.string().default(""),                // e.g. "AED"
  }).optional(),
  /** When provided, a trailing "✕" button on each row removes it. */
  removable: z.boolean().default(false),
  /** Empty-state message when rows is []. */
  emptyMessage: z.string().default("No line items. Use the lookup above to add one."),
  className: z.string().optional(),
  style:     StyleSlot.optional(),
});

export type EditableLineGridPropsType = z.infer<typeof EditableLineGridProps>;
