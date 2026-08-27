"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { RadioGroupPropsType } from "./RadioGroup.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface RadioGroupProps extends RadioGroupPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function RadioGroup({ name, label, options = [], orientation = "vertical", disabled, style, value, onChange }: RadioGroupProps) {
  return (
    <div className="flex flex-col gap-1.5" role="radiogroup" aria-label={label ?? name}
      data-radio-group="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <span className="text-sm font-medium text-foreground">{label}</span>}
      <div className={orientation === "horizontal" ? "flex flex-row gap-4" : "flex flex-col gap-2"}>
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-2 text-sm text-foreground cursor-pointer select-none">
            <input
              type="radio" name={name} value={o.value} checked={value === o.value}
              disabled={disabled || o.disabled}
              onChange={onChange ? () => onChange(o.value) : undefined}
              className="h-4 w-4 border-input text-primary accent-primary focus-visible:ring-2 focus-visible:ring-ring" />
            {o.label}
          </label>
        ))}
      </div>
    </div>
  );
}
