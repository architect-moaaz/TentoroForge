"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SliderPropsType } from "./Slider.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useFieldValue } from "../../util/useFieldValue";

export interface SliderProps extends SliderPropsType {
  style?: StyleSlotT;
  value?: number | [number, number];
  onChange?: (value: number | [number, number]) => void;
}

const REQUIRED_MARK = "ms-0.5 text-destructive";

export function Slider({
  name, label, min = 0, max = 100, step = 1, range = false, showValue, validators, style,
  value, defaultValue, onChange,
}: SliderProps) {
  // Was DEAD when rendered from a schema: `value` came straight from the prop and
  // the handler called `onChange?.()` on an onChange nobody passes, so dragging
  // the thumb changed nothing. Verified live — set to 75, reverted to 0.
  const seed: number | [number, number] = range ? [min, max] : min;
  const [current, commit] = useFieldValue<number | [number, number]>(
    value, onChange, defaultValue as number | [number, number] | undefined, seed,
  );

  const pair: [number, number] = Array.isArray(current)
    ? current
    : [typeof current === "number" ? current : min, max];
  const single = Array.isArray(current) ? current[0] : current;
  const base = "w-full accent-primary cursor-pointer";

  // A range input ALWAYS submits a value, so `required` is unenforceable here
  // and is deliberately not put on the <input>: it would be a constraint that
  // can never fail. The mark plus aria-required is the honest half — it tells
  // the author and the screen-reader user the field is expected. The bounds a
  // validator would check are the track's own `min`/`max`, which already clamp.
  const required = validators?.required === true;

  return (
    <div className="flex flex-col gap-1" data-slider="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && (
        <label className="text-sm font-medium text-foreground">
          {label}
          {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
          {showValue && (
            <span className="ms-2 text-muted-foreground">
              {range ? `${pair[0]} – ${pair[1]}` : single}
            </span>
          )}
        </label>
      )}
      {range ? (
        <div className="flex flex-col gap-1">
          <input type="range" aria-label={`${label ?? name} minimum`} min={min} max={max} step={step} value={pair[0]} className={base}
            onChange={(e) => commit([Math.min(Number(e.target.value), pair[1]), pair[1]])} />
          <input type="range" aria-label={`${label ?? name} maximum`} min={min} max={max} step={step} value={pair[1]} className={base}
            onChange={(e) => commit([pair[0], Math.max(Number(e.target.value), pair[0])])} />
          {/* Range mode rendered two NAMELESS inputs, so a range slider inside a
              Form contributed nothing to FormData at all. One hidden field
              carries the pair, mirroring Switch's hidden input. */}
          {name && <input type="hidden" name={name} value={`${pair[0]},${pair[1]}`} readOnly />}
        </div>
      ) : (
        <input type="range" name={name} aria-label={label ?? name} min={min} max={max} step={step} value={single} className={base}
          aria-required={required || undefined}
          aria-valuemin={min} aria-valuemax={max} aria-valuenow={single}
          onChange={(e) => commit(Number(e.target.value))} />
      )}
    </div>
  );
}
