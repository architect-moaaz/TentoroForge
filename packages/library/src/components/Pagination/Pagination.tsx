"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { resolveIcon } from "../../icons";

type Props = {
  currentPage: number;
  totalPages: number;
  totalItems?: number;
  pageSize?: number;
  pageSizeOptions?: number[];
  pageSizeLabel?: string;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  style?: StyleSlotT;
  className?: string;
};

const BTN_CLS =
  "inline-flex h-8 w-8 items-center justify-center rounded-md " +
  "border border-input bg-background text-foreground " +
  "hover:bg-accent hover:text-accent-foreground " +
  "disabled:cursor-not-allowed disabled:opacity-50";

const SELECT_CLS =
  "h-8 rounded-md border border-input bg-background px-2 text-sm " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function Pagination({
  currentPage,
  totalPages,
  totalItems,
  pageSize,
  pageSizeOptions,
  pageSizeLabel = "Lines per page",
  onPageChange,
  onPageSizeChange,
  style,
  className,
}: Props) {
  const Prev = resolveIcon("chevron-left");
  const Next = resolveIcon("chevron-right");
  const First = resolveIcon("chevrons-left");
  const Last = resolveIcon("chevrons-right");

  // Range string: "1-10 of 100" when totalItems + pageSize are present, else
  // the legacy "Page X of Y".
  const rangeLabel = (() => {
    if (typeof totalItems === "number" && typeof pageSize === "number") {
      const start = totalItems === 0 ? 0 : (currentPage - 1) * pageSize + 1;
      const end = Math.min(currentPage * pageSize, totalItems);
      return `${start}-${end} of ${totalItems}`;
    }
    return null;
  })();

  const canPrev = currentPage > 1;
  const canNext = currentPage < totalPages;
  const showSizeSelector =
    typeof pageSize === "number" &&
    Array.isArray(pageSizeOptions) &&
    pageSizeOptions.length > 0;

  return (
    <nav
      aria-label="Pagination"
      className={["flex items-center gap-3 text-sm text-muted-foreground", className]
        .filter(Boolean)
        .join(" ")}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {showSizeSelector && (
        <div className="flex items-center gap-2">
          <span>{pageSizeLabel}</span>
          <select
            className={SELECT_CLS}
            value={pageSize}
            onChange={
              onPageSizeChange
                ? (e) => onPageSizeChange(Number(e.target.value))
                : undefined
            }
            aria-label={pageSizeLabel}
          >
            {pageSizeOptions!.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
      )}
      {rangeLabel ? (
        <span className="tabular-nums text-foreground">{rangeLabel}</span>
      ) : (
        <span>
          Page <strong className="text-foreground">{currentPage}</strong> of{" "}
          <strong className="text-foreground">{totalPages}</strong>
        </span>
      )}
      <div className="flex items-center gap-1">
        <button
          type="button"
          className={BTN_CLS}
          disabled={!canPrev}
          aria-label="First page"
          onClick={onPageChange && canPrev ? () => onPageChange(1) : undefined}
        >
          {First && <First size={16} aria-hidden="true" />}
        </button>
        <button
          type="button"
          className={BTN_CLS}
          disabled={!canPrev}
          aria-label="Previous page"
          onClick={onPageChange && canPrev ? () => onPageChange(currentPage - 1) : undefined}
        >
          {Prev && <Prev size={16} aria-hidden="true" />}
        </button>
        <button
          type="button"
          className={BTN_CLS}
          disabled={!canNext}
          aria-label="Next page"
          onClick={onPageChange && canNext ? () => onPageChange(currentPage + 1) : undefined}
        >
          {Next && <Next size={16} aria-hidden="true" />}
        </button>
        <button
          type="button"
          className={BTN_CLS}
          disabled={!canNext}
          aria-label="Last page"
          onClick={onPageChange && canNext ? () => onPageChange(totalPages) : undefined}
        >
          {Last && <Last size={16} aria-hidden="true" />}
        </button>
      </div>
    </nav>
  );
}
