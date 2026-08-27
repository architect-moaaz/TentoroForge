import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ClusterPropsType } from "./Cluster.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { dataAttrProps, withCallerClass } from "../../util/passthroughAttrs";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";

/**
 * Inline group with consistent gap and wrapping. Naturally responsive —
 * children wrap to additional rows when the container is too narrow to fit
 * them all on one line. justify / align map to flex utilities.
 *
 * Wave 2: density token drives the default gap when props.gap is absent.
 * comfortable = 1rem (gap-4) matches today's no-gap behaviour upgraded to a
 * sensible default; existing schemas that set props.gap continue to win.
 */
const JUSTIFY_CLASS: Record<string, string> = {
  start:   "justify-start",
  center:  "justify-center",
  end:     "justify-end",
  between: "justify-between",
};
const ALIGN_CLASS: Record<string, string> = {
  start:   "items-start",
  center:  "items-center",
  end:     "items-end",
  stretch: "items-stretch",
};

function tokenVar(ref: string): string {
  return `var(--token-${ref.replace(/^tokens\./, "").replace(/\./g, "-")})`;
}

// Wave 2: density-aware default gap (CSS rem values for inline style).
// When props.gap is absent, this fallback kicks in.
// comfortable = 1rem which is the neutral default (Cluster previously had no default gap).
const DENSITY_GAP_REM: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "0.5rem",
  comfortable: "1rem",
  spacious:    "1.5rem",
};

export interface ClusterProps extends ClusterPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
  /** Schema-supplied class hook — appended to the computed class string. */
  className?: string;
  /** data-* attributes flow through validateProps; spread onto the root div. */
  [key: string]: unknown;
}

export function Cluster({
  gap,
  justify,
  align,
  equalCols,
  equalRows,
  style,
  children,
  className: callerClass,
  ...rest
}: ClusterProps) {
  const dataAttrs = dataAttrProps(rest);
  const density = useDensity();

  // Codifies the iteration-3 v4 spike CSS fix as an explicit schema-driven
  // path. The default flex+flex-wrap+justify-between Cluster is content-sized
  // — KPI tile rows look uneven because each tile shrinks to fit its label.
  // When `equalCols` is true we switch the underlying display to CSS grid
  // with N equal-width columns (minmax(0, 1fr) prevents children with long
  // content from expanding their column past the equal share). `equalRows`
  // is honoured in this branch via grid-auto-rows: 1fr.
  const useGrid = equalCols === true;
  const childCount = React.Children.count(children);

  if (useGrid) {
    const colCount = Math.max(1, childCount);
    const gridCss: React.CSSProperties = {
      display: "grid",
      gridTemplateColumns: `repeat(${colCount}, minmax(0, 1fr))`,
      gap: gap ? tokenVar(gap) : DENSITY_GAP_REM[density],
      alignItems: align === "stretch" ? "stretch"
        : align === "start"   ? "start"
        : align === "end"     ? "end"
        : "center",
      ...(equalRows === true ? { gridAutoRows: "1fr" } : {}),
      ...resolveStyle(style),
    };
    return (
      <div
        data-cluster-justify={justify}
        data-cluster-align={align}
        data-cluster-equal-cols="true"
        className={callerClass || undefined}
        style={gridCss}
        {...useMotion(style?.motion)}
        {...dataAttrs}
      >
        {children}
      </div>
    );
  }

  const className = withCallerClass(
    [
      "flex flex-row flex-wrap",
      JUSTIFY_CLASS[justify ?? "start"] ?? "justify-start",
      ALIGN_CLASS[align ?? "center"] ?? "items-center",
    ].join(" "),
    callerClass,
  );
  const css: React.CSSProperties = {
    gap: gap ? tokenVar(gap) : DENSITY_GAP_REM[density],
    ...resolveStyle(style),
  };
  return (
    <div
      data-cluster-justify={justify}
      data-cluster-align={align}
      className={className}
      style={css}
      {...useMotion(style?.motion)}
      {...dataAttrs}
    >
      {children}
    </div>
  );
}
