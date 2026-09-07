"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { InputPropsType } from "./Input.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useFieldValue } from "../../util/useFieldValue";
import { useDensity, useRadiusScale } from "../../theme/tokens-context";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { resolveIcon } from "../../icons";

/**
 * Labeled text-style input. Supports controlled value via `value` + `onChange`.
 * Validators map to native HTML attributes (required, min/maxLength, pattern).
 *
 * Uses shadcn-style Tailwind utilities so the input matches the rest of the
 * generated app's design system without component-specific CSS.
 */
export interface InputProps extends InputPropsType {
  style?: StyleSlotT;
  /** Optional controlled-mode value. */
  value?: string;
  /** Optional change handler — receives the new string value. */
  onChange?: (value: string) => void;
}

function useInputId(name: string): string {
  return `input-${name}-${React.useId()}`;
}

const DENSITY_INPUT: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "h-8 text-xs",
  comfortable: "h-10 text-sm",
  spacious:    "h-12 text-base",
};
// Padding flips depending on whether an icon is present on each side.
const DENSITY_PAD: Record<"compact" | "comfortable" | "spacious", {
  noIcon: string; left: string; right: string;
}> = {
  compact:     { noIcon: "px-2", left: "ps-7  pe-2", right: "ps-2 pe-7"  },
  comfortable: { noIcon: "px-3", left: "ps-9  pe-3", right: "ps-3 pe-9"  },
  spacious:    { noIcon: "px-4", left: "ps-11 pe-4", right: "ps-4 pe-11" },
};
const DENSITY_ICON_PX: Record<"compact" | "comfortable" | "spacious", number> = {
  compact: 14, comfortable: 16, spacious: 18,
};

const FIELD_BASE = "flex flex-col gap-1.5";
const LABEL_BASE = "text-caption font-medium leading-none text-foreground";
const REQUIRED_MARK = "ms-0.5 text-destructive";
const INPUT_STATIC =
  "flex w-full border border-input bg-background py-2 " +
  "ring-offset-background placeholder:text-muted-foreground " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

export function Input({ name, label, type, placeholder, validators, bind: _bind,
                       style, value, defaultValue, onChange, iconLeft, iconRight }: InputProps) {
  const id = useInputId(name);
  // Same conditional-controlled shape as DatePicker/TimePicker. Harmless while
  // uncontrolled, frozen the moment a `value` arrives without a handler — which
  // is exactly what a schema node supplies.
  const [current, commit] = useFieldValue<string>(
    value, onChange, defaultValue as string | undefined, "",
  );
  const required = validators?.required === true;
  const radiusScale = useRadiusScale();
  const density = useDensity();
  const LeftIconComp = iconLeft ? resolveIcon(iconLeft) : null;
  const RightIconComp = iconRight ? resolveIcon(iconRight) : null;
  const padCls = LeftIconComp && RightIconComp
    ? `ps-9 pe-9` // both — keep the comfortable spacing on each side
    : LeftIconComp
      ? DENSITY_PAD[density].left
      : RightIconComp
        ? DENSITY_PAD[density].right
        : DENSITY_PAD[density].noIcon;
  const inputCls = `${INPUT_STATIC} ${RADIUS_SURFACE_CLASS[radiusScale]} ${DENSITY_INPUT[density]} ${padCls}`;
  const iconSize = DENSITY_ICON_PX[density];
  return (
    <div
      className={FIELD_BASE}
      data-input-type={type}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {label !== undefined && (
        <div className="flex items-center gap-0.5">
          <label className={LABEL_BASE} htmlFor={id}>{label}</label>
          {/* Required indicator is a sibling of <label> so it doesn't pollute
              the accessible name (testing-library's getByLabelText("X") would
              otherwise need to match "X*"). */}
          {required && <span className={REQUIRED_MARK} aria-hidden="true">*</span>}
        </div>
      )}
      {/* Icon affordance — wrap the bare <input> in a relative container only
          when at least one icon is supplied so the no-icon case stays a flat
          single <input> element (testing-library / form serialisation
          conventions). */}
      {LeftIconComp || RightIconComp ? (
        <div className="relative">
          {LeftIconComp && (
            <LeftIconComp
              size={iconSize}
              aria-hidden="true"
              className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              data-input-icon="left"
            />
          )}
          <input
            id={id}
            className={inputCls}
            name={name}
            type={type}
            placeholder={placeholder}
            required={required}
            pattern={validators?.pattern}
            minLength={typeof validators?.min === "number" ? validators.min : undefined}
            maxLength={typeof validators?.max === "number" ? validators.max : undefined}
            value={current}
            onChange={(e) => commit(e.target.value)}
          />
          {RightIconComp && (
            <RightIconComp
              size={iconSize}
              aria-hidden="true"
              className="pointer-events-none absolute end-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              data-input-icon="right"
            />
          )}
        </div>
      ) : (
        <input
          id={id}
          className={inputCls}
          name={name}
          type={type}
          placeholder={placeholder}
          required={required}
          pattern={validators?.pattern}
          minLength={typeof validators?.min === "number" ? validators.min : undefined}
          maxLength={typeof validators?.max === "number" ? validators.max : undefined}
          value={current}
          onChange={(e) => commit(e.target.value)}
        />
      )}
    </div>
  );
}
