"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { NumberInputPropsType } from "./NumberInput.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface NumberInputProps extends NumberInputPropsType {
  style?: StyleSlotT;
  value?: number;
  onChange?: (value: number) => void;
}

function clamp(n: number, min?: number, max?: number): number {
  if (min !== undefined && n < min) return min;
  if (max !== undefined && n > max) return max;
  return n;
}

export function NumberInput({ name, label, min, max, step = 1, showSteppers = true, prefix, suffix, disabled, align, tabularNums, style, value: valueProp, onChange }: NumberInputProps) {
  const numClass = [
    align === "right" ? "text-end" : "",
    tabularNums ? "tabular-nums" : "",
  ].filter(Boolean).join(" ");
  // Controlled when a parent supplies onChange; otherwise self-manage state so the
  // +/- steppers actually work inside a plain (FormData) schema form — where no
  // onChange is wired, the value would otherwise be frozen at its initial value.
  const controlled = onChange !== undefined;
  const [internal, setInternal] = React.useState<number>(valueProp ?? 0);
  const value = controlled ? (valueProp ?? 0) : internal;
  const set = (n: number) => {
    const next = clamp(n, min, max);
    if (!controlled) setInternal(next);
    onChange?.(next);
  };
  return (
    <div className="flex flex-col gap-1" data-number-input="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}</label>}
      {showSteppers ? (
        <div className="inline-flex items-center rounded-md border border-input">
          <button type="button" aria-label="decrement" disabled={disabled} onClick={() => set(value - step)}
            className="px-2 py-1 text-foreground disabled:opacity-50">−</button>
          {prefix && <span className="ps-1 text-sm text-muted-foreground">{prefix}</span>}
          <input
            type="number" role="spinbutton" name={name} value={value} min={min} max={max} step={step} disabled={disabled}
            onChange={(e) => set(Number(e.target.value))}
            className="w-16 border-x border-input bg-transparent px-2 py-1 text-center text-sm focus-visible:outline-none" />
          {suffix && <span className="pe-1 text-sm text-muted-foreground">{suffix}</span>}
          <button type="button" aria-label="increment" disabled={disabled} onClick={() => set(value + step)}
            className="px-2 py-1 text-foreground disabled:opacity-50">+</button>
        </div>
      ) : (
        <div className="inline-flex items-center rounded-md border border-input px-2 py-1">
          {prefix && <span className="pe-1 text-sm text-muted-foreground">{prefix}</span>}
          <input
            type="text" inputMode="decimal" name={name} value={value} disabled={disabled}
            onChange={(e) => set(Number(e.target.value))}
            className={`w-full bg-transparent text-sm focus-visible:outline-none ${numClass}`.trim()} />
          {suffix && <span className="ps-1 text-sm text-muted-foreground">{suffix}</span>}
        </div>
      )}
    </div>
  );
}
