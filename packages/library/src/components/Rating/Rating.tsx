"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { RatingPropsType } from "./Rating.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { resolveIcon } from "../../icons";
import { useFieldValue } from "../../util/useFieldValue";

export interface RatingProps extends RatingPropsType {
  style?: StyleSlotT;
  value?: number;
  onChange?: (value: number) => void;
}

const REQUIRED_MARK = "ms-0.5 text-destructive";

export function Rating({ name, label, max = 5, disabled, validators, style, value, defaultValue, onChange }: RatingProps) {
  // Was DEAD when rendered from a schema: `onClick={onChange ? … : undefined}`
  // meant no handler at all, so clicking a star did nothing and the display was
  // pinned to `value = 0`. Verified live — clicked the 4th star, 0 stars filled.
  const [current, commit] = useFieldValue<number>(value, onChange, defaultValue as number | undefined, 0);
  const Star = resolveIcon("Star");
  // The stars are <button>s, not a form control, so nothing here can carry the
  // browser's `required`. What CAN be honest: mark the label and tell assistive
  // tech via aria-required on the group; the hidden input below still submits 0
  // for "not rated", which is what a server-side validator should reject.
  const required = validators?.required === true;
  return (
    <div className="flex flex-col gap-1" data-rating="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && (
        <span className="text-sm font-medium text-foreground">
          {label}
          {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
        </span>
      )}
      <div className="flex gap-0.5" role="group" aria-label={label ?? name} aria-required={required || undefined}>
        {Array.from({ length: max }).map((_, i) => {
          const n = i + 1;
          const active = n <= current;
          return (
            <button key={n} type="button" aria-label={`Rate ${n}`} aria-pressed={active} disabled={disabled}
              // Clicking the current rating clears it — otherwise a rating can be
              // raised and lowered but never withdrawn.
              onClick={() => !disabled && commit(n === current ? 0 : n)}
              className="disabled:opacity-50" style={{ color: "#fbbf24" }}>
              {Star ? <Star size={20} fill={active ? "currentColor" : "none"} aria-hidden="true" /> : (active ? "★" : "☆")}
            </button>
          );
        })}
      </div>
      {/* Rating had NO named form control of any kind — no input, no hidden
          field — so inside a Form it submitted nothing even when it worked.
          FormData reads the DOM, so the value has to exist there. */}
      {name && <input type="hidden" name={name} value={String(current)} readOnly />}
    </div>
  );
}
