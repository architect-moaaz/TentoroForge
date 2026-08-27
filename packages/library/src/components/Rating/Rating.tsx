"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { RatingPropsType } from "./Rating.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { resolveIcon } from "../../icons";

export interface RatingProps extends RatingPropsType {
  style?: StyleSlotT;
  value?: number;
  onChange?: (value: number) => void;
}

export function Rating({ name, label, max = 5, disabled, style, value = 0, onChange }: RatingProps) {
  const Star = resolveIcon("Star");
  return (
    <div className="flex flex-col gap-1" data-rating="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <span className="text-sm font-medium text-foreground">{label}</span>}
      <div className="flex gap-0.5" role="group" aria-label={label ?? name}>
        {Array.from({ length: max }).map((_, i) => {
          const n = i + 1;
          const active = n <= value;
          return (
            <button key={n} type="button" aria-label={`Rate ${n}`} aria-pressed={active} disabled={disabled}
              onClick={onChange ? () => onChange(n) : undefined}
              className="disabled:opacity-50" style={{ color: "#fbbf24" }}>
              {Star ? <Star size={20} fill={active ? "currentColor" : "none"} aria-hidden="true" /> : (active ? "★" : "☆")}
            </button>
          );
        })}
      </div>
    </div>
  );
}
