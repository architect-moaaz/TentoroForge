"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MaskedInputPropsType } from "./MaskedInput.schema";
import { applyMask } from "./MaskedInput.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

function useFieldId(name: string) { return `masked-${name}-${React.useId()}`; }

export interface MaskedInputProps extends MaskedInputPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function MaskedInput({ name, label, mask = "###", placeholder, disabled, style, value, onChange }: MaskedInputProps) {
  const id = useFieldId(name);
  const display = value !== undefined ? applyMask(value, mask) : undefined;
  return (
    <div className="flex flex-col gap-1" data-masked-input="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label htmlFor={id} className="text-sm font-medium text-foreground">{label}</label>}
      <input id={id} type="text" name={name} value={display} placeholder={placeholder} disabled={disabled}
        onChange={(e) => onChange?.(applyMask(e.target.value, mask))}
        className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
    </div>
  );
}
