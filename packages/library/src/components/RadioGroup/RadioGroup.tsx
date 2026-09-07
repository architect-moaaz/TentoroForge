"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { RadioGroupPropsType } from "./RadioGroup.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { CONTROL_COLUMN_CLASS } from "../../style/controlRow";

export interface RadioGroupProps extends RadioGroupPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function RadioGroup({ name, label, options = [], orientation = "vertical", disabled, style, value, onChange }: RadioGroupProps) {
  return (
    <div className={CONTROL_COLUMN_CLASS} role="radiogroup" aria-label={label ?? name}
      data-radio-group="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <span className="text-sm font-medium text-foreground">{label}</span>}
      <div className={orientation === "horizontal" ? "flex flex-row gap-4" : "flex flex-col gap-2"}>
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-2 text-sm text-foreground cursor-pointer select-none">
            {/* `checked` with no `onChange` is a read-only controlled input:
              * every radio renders permanently unselected and clicking does
              * nothing. A schema node supplies the prop but never a handler, so
              * without a handler the group falls back to the native uncontrolled
              * radio (same rule as Switch/Checkbox), which the browser keeps
              * mutually exclusive by `name` on its own. */}
            <input
              type="radio" name={name} value={o.value}
              disabled={disabled || o.disabled}
              {...(onChange
                ? { checked: value === o.value, onChange: () => onChange(o.value) }
                : { defaultChecked: value === o.value })}
              className="h-4 w-4 border-input text-primary accent-primary focus-visible:ring-2 focus-visible:ring-ring" />
            {o.label}
          </label>
        ))}
      </div>
    </div>
  );
}
