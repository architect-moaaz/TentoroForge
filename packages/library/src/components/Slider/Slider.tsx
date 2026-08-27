"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SliderPropsType } from "./Slider.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SliderProps extends SliderPropsType {
  style?: StyleSlotT;
  value?: number | [number, number];
  onChange?: (value: number | [number, number]) => void;
}

export function Slider({ name, label, min = 0, max = 100, step = 1, range = false, showValue, style, value, onChange }: SliderProps) {
  const pair: [number, number] = Array.isArray(value) ? value : [typeof value === "number" ? value : min, typeof value === "number" ? value : max];
  const single = typeof value === "number" ? value : min;
  const base = "w-full accent-primary cursor-pointer";
  return (
    <div className="flex flex-col gap-1" data-slider="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}{showValue && !range && <span className="ml-2 text-muted-foreground">{single}</span>}</label>}
      {range ? (
        <div className="flex flex-col gap-1">
          <input type="range" aria-label={`${label ?? name} minimum`} min={min} max={max} step={step} value={pair[0]} className={base}
            onChange={(e) => onChange?.([Number(e.target.value), pair[1]])} />
          <input type="range" aria-label={`${label ?? name} maximum`} min={min} max={max} step={step} value={pair[1]} className={base}
            onChange={(e) => onChange?.([pair[0], Number(e.target.value)])} />
        </div>
      ) : (
        <input type="range" name={name} aria-label={label ?? name} min={min} max={max} step={step} value={single} className={base}
          aria-valuemin={min} aria-valuemax={max} aria-valuenow={single}
          onChange={(e) => onChange?.(Number(e.target.value))} />
      )}
    </div>
  );
}
