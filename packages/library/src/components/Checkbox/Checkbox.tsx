"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CheckboxPropsType } from "./Checkbox.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useRadiusScale } from "../../theme/tokens-context";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { CONTROL_ROW_CLASS } from "../../style/controlRow";

/**
 * Checkbox with side-by-side label. Uses native <input type="checkbox"> with
 * shadcn-style accent color and focus ring so it matches the generated app.
 */
export interface CheckboxProps extends CheckboxPropsType {
  style?: StyleSlotT;
  /** Controlled checked state. */
  checked?: boolean;
  /** Change handler — receives new boolean value. */
  onChange?: (checked: boolean) => void;
}

function useCheckboxId(name: string): string {
  return `checkbox-${name}-${React.useId()}`;
}

export function Checkbox({ name, label, validators: _v, bind: _bind,
                          style, checked, onChange }: CheckboxProps) {
  const id = useCheckboxId(name);
  const radiusScale = useRadiusScale();
  const checkboxCls = `h-4 w-4 ${RADIUS_SURFACE_CLASS[radiusScale]} border-input text-primary accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2`;
  return (
    <div
      className={CONTROL_ROW_CLASS}
      data-checkbox=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {/* `checked` without `onChange` is React's read-only controlled input —
        * the box renders but can never be ticked. A schema node can only ever
        * supply the prop, never the handler, so a declarative `checked` is
        * treated as the INITIAL value (`defaultChecked`) and the input stays
        * uncontrolled. Same defect and same rule as Switch. */}
      <input
        id={id}
        type="checkbox"
        className={checkboxCls}
        name={name}
        {...(onChange
          ? { checked, onChange: (e: React.ChangeEvent<HTMLInputElement>) => onChange(e.target.checked) }
          : { defaultChecked: checked })}
      />
      <label
        className="text-sm font-medium leading-none text-foreground cursor-pointer select-none"
        htmlFor={id}
      >
        {label}
      </label>
    </div>
  );
}
