"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SpinnerPropsType } from "./Spinner.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { paintOr } from "../../util/paint";

export interface SpinnerProps extends SpinnerPropsType {
  style?: StyleSlotT;
}

const SIZE: Record<string, string> = { sm: "h-4 w-4 border-2", md: "h-6 w-6 border-2", lg: "h-8 w-8 border-[3px]" };
/** Dot / bar diameters per size, so the three variants read at the same weight. */
const DOT: Record<string, string> = { sm: "h-1.5 w-1.5", md: "h-2 w-2", lg: "h-2.5 w-2.5" };
const BAR: Record<string, string> = { sm: "h-3 w-0.5", md: "h-4 w-1", lg: "h-5 w-1" };

/**
 * Spinner.
 *
 * THE COLOUR IS A PROP, NOT A CONSTANT.
 * -------------------------------------
 * The arc was hardwired to `border-t-primary`, and `resolveStyle(style)` lands
 * on the OUTER span — so a Spinner placed on a primary-coloured surface (a
 * filled Hero, a primary button) was invisible and nothing in the Style panel
 * could fix it. `color` overrides just the moving part and accepts
 * `currentColor`, which is what you want on a coloured surface: the spinner
 * then inherits whatever the surrounding text is already using.
 *
 * Absent `color` keeps the exact previous rendering, so no shipped app moves.
 */
export function Spinner({ label = "Loading", size = "md", variant = "ring", color, style }: SpinnerProps) {
  const sizeKey = SIZE[size] ? size : "md";
  // `paintOr` rather than a parameter default: a `""` arriving from a colour
  // control or a seed is present-and-blank, and a parameter default only fires
  // for `undefined`. See util/paint — the Sparkline "draws nothing" bug.
  const ink = paintOr(color, "");
  const tint = ink ? { backgroundColor: ink } : undefined;

  let indicator: React.ReactNode;
  if (variant === "dots") {
    indicator = (
      <span className="inline-flex items-center gap-1" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={`${DOT[sizeKey]} animate-pulse rounded-full ${ink ? "" : "bg-primary"}`}
            style={{ ...tint, animationDelay: `${i * 150}ms` }}
          />
        ))}
      </span>
    );
  } else if (variant === "bars") {
    indicator = (
      <span className="inline-flex items-end gap-0.5" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={`${BAR[sizeKey]} animate-pulse rounded-sm ${ink ? "" : "bg-primary"}`}
            style={{ ...tint, animationDelay: `${i * 120}ms` }}
          />
        ))}
      </span>
    );
  } else {
    indicator = (
      <span
        aria-hidden="true"
        // The track stays `border-muted`; only the arc takes the colour, so a
        // custom colour still reads as a spinner rather than a solid ring.
        className={`${SIZE[sizeKey]} animate-spin rounded-full border-muted ${ink ? "" : "border-t-primary"}`}
        style={ink ? { borderTopColor: ink } : undefined}
      />
    );
  }

  return (
    <span role="status" aria-label={label} data-spinner="" data-spinner-variant={variant}
      style={resolveStyle(style)} {...useMotion(style?.motion)}
      className="inline-flex items-center">
      {indicator}
      <span className="sr-only">{label}</span>
    </span>
  );
}
