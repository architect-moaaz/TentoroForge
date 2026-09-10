"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MaskedInputPropsType } from "./MaskedInput.schema";
import { applyMask } from "./MaskedInput.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useFieldValue } from "../../util/useFieldValue";

function useFieldId(name: string) { return `masked-${name}-${React.useId()}`; }

export interface MaskedInputProps extends MaskedInputPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function MaskedInput({ name, label, mask = "###", placeholder, disabled, style, value, defaultValue, onChange }: MaskedInputProps) {
  const id = useFieldId(name);
  // Was conditionally controlled: given a `value` and no handler it froze, and
  // when uncontrolled the mask never ran at all — the whole point of the
  // component only worked if a parent happened to own its state.
  const [current, commit] = useFieldValue<string>(
    value, onChange, defaultValue as string | undefined, "",
  );
  const display = applyMask(current, mask);
  return (
    <div className="flex flex-col gap-1" data-masked-input="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label htmlFor={id} className="text-sm font-medium text-foreground">{label}</label>}
      <input id={id} type="text" name={name} value={display} placeholder={placeholder} disabled={disabled}
        onChange={(e) => commit(applyMask(e.target.value, mask))}
        className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
    </div>
  );
}
