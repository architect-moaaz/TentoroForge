"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SelectPropsType } from "./Select.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity, useRadiusScale } from "../../theme/tokens-context";

/**
 * Labeled native <select>. Options come from props.options[].
 *
 * Uses shadcn-style Tailwind utilities so the select matches the rest of the
 * generated app's design system without component-specific CSS.
 */
export interface SelectProps extends SelectPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

function useSelectId(name: string): string {
  return `select-${name}-${React.useId()}`;
}

const RADIUS_CLASS: Record<"sharp" | "soft" | "round", string> = {
  sharp: "rounded-sm",
  soft:  "rounded-md",
  round: "rounded-lg",
};

const DENSITY_INPUT: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "h-8 px-2 text-xs",
  comfortable: "h-10 px-3 text-sm",
  spacious:    "h-12 px-4 text-base",
};

const FIELD_BASE = "flex flex-col gap-1.5";
const LABEL_BASE = "text-sm font-medium leading-none text-foreground";
const REQUIRED_MARK = "ms-0.5 text-destructive";
const SELECT_STATIC =
  "flex w-full items-center justify-between border border-input " +
  "bg-background py-2 ring-offset-background " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

export function Select(props: SelectProps) {
  const { name, label, options, validators, style, value, onChange } = props;
  const inlineAdd = (props as { inlineAdd?: { route: string; label?: string } }).inlineAdd;
  const id = useSelectId(name);
  const required = validators?.required === true;
  const radiusScale = useRadiusScale();
  const density = useDensity();
  const selectCls = `${SELECT_STATIC} ${RADIUS_CLASS[radiusScale]} ${DENSITY_INPUT[density]}`;
  // Empty-options inline-add UX: when this Select's `optionsFrom` returned
  // no rows AND the schema supplied an inlineAdd route, replace the dead-
  // end empty dropdown with an "+ Add new X" link into the create form.
  // Root-cause fix for the B-021.8 UX class (empty FK dropdown blocks
  // form submission across every generated app).
  const hasOptions = Array.isArray(options) && options.length > 0;
  if (!hasOptions && inlineAdd?.route) {
    const addLabel = inlineAdd.label || `+ Add ${label?.toLowerCase() || "option"}`;
    return (
      <div
        className={FIELD_BASE}
        data-select=""
        data-empty-options="true"
        style={resolveStyle(style)}
        {...useMotion(style?.motion)}
      >
        <div className="flex items-center gap-0.5">
          <label className={LABEL_BASE} htmlFor={id}>{label}</label>
          {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
        </div>
        <a
          href={inlineAdd.route}
          className={`${selectCls} text-muted-foreground hover:text-foreground hover:border-input`}
          data-inline-add=""
        >
          <span>{addLabel}</span>
          <span aria-hidden>→</span>
        </a>
      </div>
    );
  }
  return (
    <div
      className={FIELD_BASE}
      data-select=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      <div className="flex items-center gap-0.5">
        <label className={LABEL_BASE} htmlFor={id}>{label}</label>
        {/* Required indicator outside <label> so getByLabelText still matches. */}
        {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
      </div>
      <select
        id={id}
        className={selectCls}
        name={name}
        required={required}
        value={value}
        onChange={onChange ? (e) => onChange(e.target.value) : undefined}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}
