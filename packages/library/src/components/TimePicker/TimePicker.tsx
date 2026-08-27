"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { TimePickerPropsType } from "./TimePicker.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

function useFieldId(name: string) { return `time-${name}-${React.useId()}`; }

export interface TimePickerProps extends TimePickerPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function TimePicker({ name, label, min, max, step, disabled, style, value, onChange }: TimePickerProps) {
  const id = useFieldId(name ?? "time");
  return (
    <div className="flex flex-col gap-1" data-time-picker="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label htmlFor={id} className="text-sm font-medium text-foreground">{label}</label>}
      <input id={id} type="time" name={name} value={value} min={min} max={max} step={step} disabled={disabled}
        onChange={onChange ? (e) => onChange(e.target.value) : undefined}
        className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
    </div>
  );
}
