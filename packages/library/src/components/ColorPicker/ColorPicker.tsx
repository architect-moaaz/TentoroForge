"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ColorPickerPropsType } from "./ColorPicker.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface ColorPickerProps extends ColorPickerPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function ColorPicker({ name, label, disabled, style, value = "#000000", onChange }: ColorPickerProps) {
  return (
    <div className="flex flex-col gap-1" data-color-picker="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <span className="text-sm font-medium text-foreground">{label}</span>}
      <div className="inline-flex items-center gap-2">
        <input data-testid="color-input" type="color" name={name} value={value} disabled={disabled}
          onChange={onChange ? (e) => onChange(e.target.value) : undefined}
          aria-label={label ?? name}
          className="h-8 w-10 cursor-pointer rounded border border-input bg-transparent p-0.5" />
        <span className="font-mono text-xs text-muted-foreground">{value}</span>
      </div>
    </div>
  );
}
