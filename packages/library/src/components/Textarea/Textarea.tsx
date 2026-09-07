"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { TextareaPropsType } from "./Textarea.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useFieldValue } from "../../util/useFieldValue";
import { useDensity, useRadiusScale } from "../../theme/tokens-context";

/**
 * Multi-line text input. Defaults to 4 rows.
 *
 * Uses shadcn-style Tailwind utilities so the textarea matches the rest of
 * the generated app's design system without component-specific CSS.
 */
export interface TextareaProps extends TextareaPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

function useTextareaId(name: string): string {
  return `textarea-${name}-${React.useId()}`;
}

const RADIUS_CLASS: Record<"sharp" | "soft" | "round", string> = {
  sharp: "rounded-sm",
  soft:  "rounded-md",
  round: "rounded-lg",
};

const DENSITY_TEXTAREA: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "px-2 text-xs",
  comfortable: "px-3 text-sm",
  spacious:    "px-4 text-base",
};

const FIELD_BASE = "flex flex-col gap-1.5";
const LABEL_BASE = "text-sm font-medium leading-none text-foreground";
const REQUIRED_MARK = "ms-0.5 text-destructive";
const TEXTAREA_STATIC =
  "flex min-h-[80px] w-full border border-input bg-background py-2 " +
  "ring-offset-background placeholder:text-muted-foreground " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 " +
  "resize-y";

export function Textarea({ name, label, rows = 4, placeholder, validators, bind: _bind,
                          style, value, defaultValue, onChange }: TextareaProps) {
  const id = useTextareaId(name);
  const [current, commit] = useFieldValue<string>(
    value, onChange, defaultValue as string | undefined, "",
  );
  const required = validators?.required === true;
  const radiusScale = useRadiusScale();
  const density = useDensity();
  const textareaCls = `${TEXTAREA_STATIC} ${RADIUS_CLASS[radiusScale]} ${DENSITY_TEXTAREA[density]}`;
  return (
    <div
      className={FIELD_BASE}
      data-textarea=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      <div className="flex items-center gap-0.5">
        <label className={LABEL_BASE} htmlFor={id}>{label}</label>
        {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
      </div>
      <textarea
        id={id}
        className={textareaCls}
        name={name}
        rows={rows}
        placeholder={placeholder}
        required={required}
        value={current}
        onChange={(e) => commit(e.target.value)}
      />
    </div>
  );
}
