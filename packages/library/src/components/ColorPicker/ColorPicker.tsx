"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ColorPickerPropsType } from "./ColorPicker.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useFieldValue } from "../../util/useFieldValue";

export interface ColorPickerProps extends ColorPickerPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

const REQUIRED_MARK = "ms-0.5 text-destructive";

export function ColorPicker({ name, label, disabled, validators, style, value, defaultValue, onChange }: ColorPickerProps) {
  // Was the LOUDEST of the dead controls: `value = "#000000"` defaulted at the
  // parameter, `onChange` absent, so React itself warned "You provided a `value`
  // prop to a form field without an `onChange` handler. This will render a
  // read-only field." That warning is what surfaced in the editor as a standing
  // "1 Issue" badge. Verified live — set to #ff0000, reverted to #000000.
  const [current, commit] = useFieldValue<string>(
    value, onChange, defaultValue as string | undefined, "#000000",
  );
  // `required` on <input type="color"> is inert — the control always has a
  // value (#000000 when untouched), so the browser can never fail it. The mark
  // and aria-required are what a required ColorPicker can honestly express;
  // "the user must actually pick one" needs a sentinel value, not a validator.
  const required = validators?.required === true;
  return (
    <div className="flex flex-col gap-1" data-color-picker="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && (
        <span className="text-sm font-medium text-foreground">
          {label}
          {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
        </span>
      )}
      <div className="inline-flex items-center gap-2">
        <input data-testid="color-input" type="color" name={name} value={current} disabled={disabled}
          onChange={(e) => commit(e.target.value)}
          aria-required={required || undefined}
          aria-label={label ?? name}
          className="h-8 w-10 cursor-pointer rounded border border-input bg-transparent p-0.5" />
        <span className="font-mono text-xs text-muted-foreground">{current}</span>
      </div>
    </div>
  );
}
