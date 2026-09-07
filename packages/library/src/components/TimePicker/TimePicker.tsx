"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { TimePickerPropsType } from "./TimePicker.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useFieldValue } from "../../util/useFieldValue";

function useFieldId(name: string) { return `time-${name}-${React.useId()}`; }

export interface TimePickerProps extends TimePickerPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

const REQUIRED_MARK = "ms-0.5 text-destructive";

export function TimePicker({ name, label, min, max, step, disabled, validators, style, value, defaultValue, onChange }: TimePickerProps) {
  const id = useFieldId(name ?? "time");
  // `validators` reached the NODE schema through baseField but never reached
  // this component, so a required time field could be declared and then quietly
  // submitted empty. <input type="time"> enforces `required` natively.
  const required = validators?.required === true;
  // The QUIET half of the dead-input split. With no `value` it was natively
  // uncontrolled, so typing worked and nothing warned — but the value lived only
  // in the DOM and no declarative prefill was possible. With a `value` and no
  // handler it froze, exactly like ColorPicker.
  const [current, commit] = useFieldValue<string>(
    value, onChange, defaultValue as string | undefined, "",
  );
  return (
    <div className="flex flex-col gap-1" data-time-picker="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && (
        <label htmlFor={id} className="text-sm font-medium text-foreground">
          {label}
          {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
        </label>
      )}
      <input id={id} type="time" name={name} value={current} min={min} max={max} step={step} disabled={disabled} required={required}
        onChange={(e) => commit(e.target.value)}
        className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
    </div>
  );
}
