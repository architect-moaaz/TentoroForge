import { useVirtualizer } from "@tanstack/react-virtual";
import * as React from "react";

/**
 * Thin wrapper around @tanstack/react-virtual's useVirtualizer.
 * Provides overscan=5 and height-based estimation for DataGrid rows.
 */
export function useVirtualRows(
  scrollRef: React.RefObject<HTMLDivElement | null>,
  rowCount: number,
  rowHeight: number,
) {
  return useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 5,
  });
}
