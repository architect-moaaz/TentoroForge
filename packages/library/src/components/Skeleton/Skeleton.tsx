import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SkeletonPropsType } from "./Skeleton.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useRadiusScale } from "../../theme/tokens-context";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";

/**
 * Skeleton — loading placeholder. variant=rect → block, circle → round,
 * text → 1+ lines. For text variant, `lines` (default 1) controls the
 * number of stacked lines. Renders with shadcn-style animate-pulse so the
 * shimmer matches the rest of the generated app.
 */
export interface SkeletonProps extends SkeletonPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

const BASE = "animate-pulse bg-muted";

export function Skeleton({ variant, lines, style }: SkeletonProps) {
  const css = resolveStyle(style);
  const motion = useMotion(style?.motion);
  const radiusScale = useRadiusScale();

  if (variant === "text") {
    const n = lines ?? 1;
    return (
      <span
        className="flex flex-col gap-2"
        data-skeleton-variant="text"
        style={css}
        {...motion}
      >
        {Array.from({ length: n }, (_, i) => (
          <span
            key={i}
            className={`${BASE} h-4 ${RADIUS_SURFACE_CLASS[radiusScale]} ${i === n - 1 && n > 1 ? "w-2/3" : "w-full"}`}
            aria-hidden="true"
          />
        ))}
      </span>
    );
  }

  const shapeCls =
    variant === "circle"
      ? "rounded-full h-10 w-10"
      : `${RADIUS_SURFACE_CLASS[radiusScale]} h-16 w-full`;
  return (
    <span
      className={`block ${BASE} ${shapeCls}`}
      data-skeleton-variant={variant}
      style={css}
      {...motion}
      aria-hidden="true"
    />
  );
}
