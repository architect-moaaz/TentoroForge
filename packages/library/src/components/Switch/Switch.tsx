"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SwitchPropsType } from "./Switch.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SwitchProps extends SwitchPropsType {
  style?: StyleSlotT;
  /** Controlled value. When omitted the Switch manages its own state. */
  checked?: boolean;
  /** Initial value for the uncontrolled case. */
  defaultChecked?: boolean;
  /** Declarative prefill (schema binding) — boolean or "true"/"false". */
  defaultValue?: boolean | string;
  onChange?: (checked: boolean) => void;
}

const asBool = (v: unknown): boolean => v === true || v === "true" || v === "on" || v === 1;

export function Switch({
  name, label, disabled, size = "md", style,
  checked, defaultChecked, defaultValue, onChange,
}: SwitchProps) {
  // Self-managing by default: rendered declaratively from a schema node it gets
  // no onChange/checked, so without internal state the button is dead and its
  // value never reaches the form. Fall back to controlled when `checked` is set.
  const isControlled = checked !== undefined;
  const [internal, setInternal] = React.useState<boolean>(
    () => checked ?? defaultChecked ?? asBool(defaultValue),
  );
  const on = isControlled ? (checked as boolean) : internal;

  const toggle = () => {
    if (disabled) return;
    const next = !on;
    if (!isControlled) setInternal(next);
    onChange?.(next);
  };

  const track = size === "sm" ? "h-4 w-7" : "h-5 w-9";
  const knob = size === "sm" ? "h-3 w-3" : "h-4 w-4";
  const shift = on ? (size === "sm" ? "translate-x-3.5" : "translate-x-4") : "translate-x-0.5";
  return (
    <div className="flex items-center gap-2" data-switch="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label ?? name}
        disabled={disabled}
        onClick={toggle}
        className={`relative inline-flex ${track} shrink-0 cursor-pointer items-center rounded-full transition-colors ${on ? "bg-primary" : "bg-input"} disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
      >
        <span className={`${knob} ${shift} inline-block transform rounded-full bg-white shadow transition-transform`} />
      </button>
      {label && <label className="text-sm font-medium text-foreground select-none" onClick={toggle}>{label}</label>}
      {/* Carry the value into the enclosing form's FormData under `name`. */}
      {name && <input type="hidden" name={name} value={on ? "true" : "false"} />}
    </div>
  );
}
