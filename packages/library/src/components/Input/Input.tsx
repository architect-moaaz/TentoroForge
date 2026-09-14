"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { InputPropsType } from "./Input.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity, useRadiusScale } from "../../theme/tokens-context";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { resolveIcon } from "../../icons";
import { useUrlState } from "../../style/useUrlState";

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

/**
 * `validation` — the registry's "Validation rule expression." It had a live
 * text control in the editor, was stripped by the zod schema, and was never
 * read here: a user could type a rule, watch it save, and get no validation.
 *
 * It is the compact form of the `validators` object this component already
 * honours, so it is parsed INTO that shape rather than given a second,
 * divergent enforcement path. Grammar, deliberately small:
 *
 *   required                 the field must be filled
 *   email                    must look like an address
 *   min:N / minLength:N      minimum length
 *   max:N / maxLength:N      maximum length
 *   pattern:<regex>          raw HTML pattern
 *
 * Rules are separated by `|` or `,`. `pattern:` takes the whole remainder of
 * the expression, so a regex may itself contain `|` — which means it has to be
 * written last. Anything unrecognised is ignored rather than throwing: a typo
 * in a text box must not blank out the page.
 */
const EMAIL_PATTERN = "[^@\\s]+@[^@\\s]+\\.[^@\\s]+";

type InputValidators = NonNullable<InputPropsType["validators"]>;

export function parseValidation(expr: unknown): InputValidators {
  const out: InputValidators = {};
  if (typeof expr !== "string" || !expr.trim()) return out;
  let head = expr;
  const patAt = expr.search(/\bpattern\s*:/i);
  if (patAt >= 0) {
    head = expr.slice(0, patAt);
    const pat = expr.slice(patAt).replace(/^\s*pattern\s*:\s*/i, "").trim();
    if (pat) out.pattern = pat;
  }
  for (const raw of head.split(/[|,]/)) {
    const rule = raw.trim();
    if (!rule) continue;
    const colon = rule.indexOf(":");
    const key = (colon >= 0 ? rule.slice(0, colon) : rule).trim().toLowerCase();
    const arg = colon >= 0 ? rule.slice(colon + 1).trim() : "";
    const n = Number(arg);
    if (key === "required") out.required = true;
    else if (key === "email") { if (out.pattern === undefined) out.pattern = EMAIL_PATTERN; }
    else if ((key === "min" || key === "minlength") && arg !== "" && Number.isFinite(n)) out.minLength = n;
    else if ((key === "max" || key === "maxlength") && arg !== "" && Number.isFinite(n)) out.maxLength = n;
  }
  return out;
}

/**
 * The two vocabularies overlap on the same BOUND under different names: the
 * expression writes `minLength`, an object may write `min`, and the component
 * below prefers the HTML-standard spelling. A plain `{...parsed, ...explicit}`
 * therefore let the expression's `minLength:3` beat an explicit `min:9` — the
 * opposite of the intended precedence, and invisible in a spread.
 *
 * So a bound the object sets under EITHER spelling clears the expression's.
 */
function mergeValidation(
  parsed: InputValidators,
  explicit: InputValidators | undefined,
): InputValidators {
  if (!explicit) return parsed;
  const out: InputValidators = { ...parsed };
  if (explicit.min !== undefined || explicit.minLength !== undefined) delete out.minLength;
  if (explicit.max !== undefined || explicit.maxLength !== undefined) delete out.maxLength;
  return { ...out, ...explicit };
}

const FIELD_BASE = "flex flex-col gap-1.5";
const LABEL_BASE = "text-caption font-medium leading-none text-foreground";
const REQUIRED_MARK = "ms-0.5 text-destructive";
const INPUT_STATIC =
  "flex w-full border border-input bg-background py-2 " +
  "ring-offset-background placeholder:text-muted-foreground " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

export function Input({ name, label, type, placeholder, validators: validatorsProp,
                       validation, bind: _bind,
                       style, value, onChange, iconLeft, iconRight }: InputProps) {
  const id = useInputId(name);
  // Both vocabularies may arrive together. The structured object is the
  // higher-fidelity source, so it wins key by key; the expression fills only
  // what it leaves unset.
  const validators = React.useMemo(
    () => mergeValidation(parseValidation(validation), validatorsProp),
    [validation, validatorsProp],
  );
  const required = validators?.required === true;
  // Both vocabularies apply as string length; the explicit HTML-standard
  // `minLength`/`maxLength` win over the historic `min`/`max`.
  const minLen = typeof validators?.minLength === "number" ? validators.minLength
    : typeof validators?.min === "number" ? validators.min : undefined;
  const maxLen = typeof validators?.maxLength === "number" ? validators.maxLength
    : typeof validators?.max === "number" ? validators.max : undefined;
  // THE PAGE'S SEARCH BOX. `type: "search"` writes `q` to the URL (debounced),
  // which the page passes to its list source's `search`; the searchable
  // columns manifest decides what it matches. A drawn "Search policies…"
  // box becomes this, and the list it sits above is what it searches.
  const isSearch = type === "search";
  const [urlQ, setUrlQ] = useUrlState("q", "");
  const [draft, setDraft] = React.useState<string>(urlQ);
  React.useEffect(() => {
    if (!isSearch) return;
    const t = setTimeout(() => { if (draft !== urlQ) setUrlQ(draft); }, 300);
    return () => clearTimeout(t);
  }, [draft, isSearch, urlQ, setUrlQ]);
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
            name={isSearch ? (name || "q") : name}
            type={type}
            placeholder={placeholder}
            required={required}
            pattern={validators?.pattern}
            minLength={minLen}
            maxLength={maxLen}
            value={isSearch ? draft : value}
            onChange={isSearch ? (e) => setDraft(e.target.value) : onChange ? (e) => onChange(e.target.value) : undefined}
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
          name={isSearch ? (name || "q") : name}
          type={type}
          placeholder={placeholder}
          required={required}
          pattern={validators?.pattern}
          minLength={minLen}
          maxLength={maxLen}
          value={isSearch ? draft : value}
          onChange={isSearch ? (e) => setDraft(e.target.value) : onChange ? (e) => onChange(e.target.value) : undefined}
        />
      )}
    </div>
  );
}
