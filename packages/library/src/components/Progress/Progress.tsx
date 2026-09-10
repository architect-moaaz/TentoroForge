"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ProgressPropsType } from "./Progress.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface ProgressProps extends ProgressPropsType {
  style?: StyleSlotT;
  value?: number;
}

export function Progress({ label, value = 0, max = 100, variant = "bar", showValue, style }: ProgressProps) {
  const pct = Math.max(0, Math.min(100, max ? (value / max) * 100 : 0));
  const now = Math.round(pct);
  if (variant === "circular") {
    const r = 18, c = 2 * Math.PI * r;
    return (
      <div className="inline-flex flex-col items-center gap-1" data-progress="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
        <svg width="44" height="44" role="progressbar" aria-valuenow={now} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
          <circle cx="22" cy="22" r={r} fill="none" stroke="currentColor" strokeWidth="4" className="text-muted" />
          <circle cx="22" cy="22" r={r} fill="none" stroke="currentColor" strokeWidth="4" className="text-primary"
            strokeDasharray={c} strokeDashoffset={c - (pct / 100) * c} strokeLinecap="round" transform="rotate(-90 22 22)" />
        </svg>
        {/* THE RING USED TO BE THE ONLY THING THIS BRANCH RENDERED.
            `label` was passed to `aria-label` and dropped on the floor
            visually, so a circular Progress in a generated app was a
            decorative arc: no words, and — before `showValue` had a control —
            no number either. A sighted user could see that something was some
            fraction of the way along and nothing about what. The bar branch
            below has always drawn its label; the two branches simply
            disagreed. `aria-label` still carries it for assistive tech, and
            the visible copy is now the same copy. */}
        {showValue && <span className="text-xs text-muted-foreground">{now}%</span>}
        {label && <span className="text-sm text-foreground">{label}</span>}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1" data-progress="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <div className="flex justify-between text-sm"><span className="text-foreground">{label}</span>{showValue && <span className="text-muted-foreground">{now}%</span>}</div>}
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={now} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
