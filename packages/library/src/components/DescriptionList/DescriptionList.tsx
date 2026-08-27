"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { DescriptionListPropsType } from "./DescriptionList.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { formatValue } from "../../utils/formatValue";
import { ensureHumanLabel, humanizeLabel } from "../../utils/humanizeLabel";
import { SCROLL_X } from "../../style/scroll";

export interface DescriptionListProps extends DescriptionListPropsType { style?: StyleSlotT; }

export function DescriptionList(props: DescriptionListProps) {
  const { items, dataSource, itemMode, emptyText, orientation = "vertical", style } = props as any;
  const horizontal = orientation === "horizontal";
  // Derive rows from whichever source the schema supplied. `dataSource`
  // (an object/array bound from a data source) wins when itemMode="entries"
  // so a detail page can bind e.g. a jsonb `extractedFields` column and
  // render one row per key without any Python-side reshaping. `items` may
  // arrive as undefined, an unresolved binding string, or a non-array
  // shape the schema didn't predict — never let it crash render. Also
  // normalize the {label, value} shape to {term, description}.
  let rows: Array<{ term?: unknown; description?: unknown; label?: unknown; value?: unknown }> = [];
  if (itemMode === "entries" || (dataSource && !items?.length)) {
    if (dataSource && typeof dataSource === "object" && !Array.isArray(dataSource)) {
      // Keys here ARE raw data keys (jsonb columns like "document_5_tax")
      // — always humanize; no generation-time pass ever sees them.
      rows = Object.entries(dataSource as Record<string, unknown>).map(([k, v]) => ({ term: humanizeLabel(k), description: v }));
    } else if (Array.isArray(dataSource)) {
      rows = dataSource as any[];
    }
  } else if (Array.isArray(items)) {
    rows = items;
  }
  // Empty-state — an explicit `emptyText` lets the schema author show a
  // human hint ("No fields extracted yet.") rather than a bare divider.
  if (rows.length === 0 && !props.isLoading) {
    if (!emptyText) return null;
    return (
      <p className="text-sm text-muted-foreground" data-description-list="" data-empty="true" style={resolveStyle(style)}>
        {emptyText}
      </p>
    );
  }
  // Loading skeleton — matches the row count in the loaded state so the
  // detail view doesn't reflow on data arrival. Root-cause fix for CLS.
  if (props.isLoading) {
    const rowCount = Math.max(3, props.skeletonRows ?? 6);
    return (
      <dl
        className={`divide-y divide-border ${SCROLL_X}`}
        data-description-list=""
        data-loading="true"
        data-orientation={orientation}
        style={resolveStyle(style)}
        {...useMotion(style?.motion)}
      >
        {Array.from({ length: rowCount }).map((_, i) => (
          <div key={i} className={horizontal ? "flex justify-between gap-4 py-2" : "py-2"}>
            <div className="h-3 w-24 animate-pulse rounded bg-muted" aria-hidden />
            <div className="mt-2 h-3 animate-pulse rounded bg-muted" style={{ width: `${40 + (i * 9) % 40}%` }} aria-hidden />
          </div>
        ))}
      </dl>
    );
  }
  return (
    <dl className={`divide-y divide-border ${SCROLL_X}`} data-description-list="" data-orientation={orientation} style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {rows.map((it: any, i: number) => {
        // Accept both {term, description} (canonical) and {label, value}
        // (LLM-emitted). Coerce non-primitives (Date/number/object from a
        // jsonb column) via formatValue so no child ever throws
        // `Objects are not valid as a React child`.
        const rawTerm = it == null ? "" : (it.term ?? it.label);
        const rawDesc = it == null ? "" : (it.description ?? it.value);
        // Authored labels pass through; machine-looking ones ("createdAt",
        // "tax_year") get humanized — renderer-level raw-key guarantee.
        const term = ensureHumanLabel(formatValue(rawTerm));
        const description = formatValue(rawDesc);
        return (
          <div key={i} className={horizontal ? "flex justify-between gap-4 py-2" : "py-2"}>
            <dt className="text-sm font-medium text-muted-foreground">{term}</dt>
            <dd className="text-sm text-foreground">{description}</dd>
          </div>
        );
      })}
    </dl>
  );
}
