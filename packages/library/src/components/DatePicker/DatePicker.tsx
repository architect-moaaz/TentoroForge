"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { DatePickerPropsType } from "./DatePicker.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity, useRadiusScale } from "../../theme/tokens-context";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";

/**
 * DatePicker — native <input type="date"> with shadcn-style chrome so it
 * matches the rest of the generated app's form fields. ISO 8601 date
 * strings (YYYY-MM-DD) for value/min/max.
 */
export interface DatePickerProps extends DatePickerPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

function useDatePickerId(name: string): string {
  return `date-${name}-${React.useId()}`;
}

const DENSITY_INPUT: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "h-8 px-2 text-xs",
  comfortable: "h-10 px-3 text-sm",
  spacious:    "h-12 px-4 text-base",
};

const FIELD_BASE = "flex flex-col gap-1.5";
const LABEL_BASE = "text-sm font-medium leading-none text-foreground";
const REQUIRED_MARK = "ml-0.5 text-destructive";
const INPUT_STATIC =
  "flex w-full border border-input bg-background py-2 " +
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed " +
  "disabled:opacity-50";

export function DatePicker({ name, label, min, max, validators, bind: _bind,
                            style, value, onChange }: DatePickerProps) {
  const id = useDatePickerId(name);
  const required = validators?.required === true;
  const radiusScale = useRadiusScale();
  const density = useDensity();
  const inputCls = `${INPUT_STATIC} ${RADIUS_SURFACE_CLASS[radiusScale]} ${DENSITY_INPUT[density]}`;
  return (
    <div
      className={FIELD_BASE}
      data-date-picker=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      <div className="flex items-center gap-0.5">
        <label className={LABEL_BASE} htmlFor={id}>{label}</label>
        {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
      </div>
      <input
        id={id}
        type="date"
        className={inputCls}
        name={name}
        min={min}
        max={max}
        required={required}
        value={value}
        onChange={onChange ? (e) => onChange(e.target.value) : undefined}
      />
    </div>
  );
}
