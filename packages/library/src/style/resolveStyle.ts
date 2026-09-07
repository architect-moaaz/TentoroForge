// packages/library/src/style/resolveStyle.ts
import type { CSSProperties } from "react";
import type { StyleSlotT, BackgroundT } from "@tentoroforge/schema";

function tokenVar(ref: string): string {
  // tokens.color.primary.500 → var(--token-color-primary-500)
  return `var(--token-${ref.replace(/^tokens\./, "").replace(/\./g, "-")})`;
}

/**
 * Token-vs-raw discrimination, kept byte-for-byte in step with the renderer's
 * runtime/style-slot.ts (isColorTokenRef / isScaleTokenRef).
 *
 * Deliberately duplicated rather than imported — that module is itself an
 * inlined copy so the renderer need not depend on this package, and adding the
 * reverse dependency to share one regex would create the cycle both copies
 * exist to avoid. The two MUST agree: a background painted one way by a
 * structural Box and another by a library Card is worse than either behaviour
 * on its own.
 */
const TOKEN_REF_SHAPE = /^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*$/;
const CSS_KEYWORDS = new Set([
  "auto", "none", "normal", "bold", "bolder", "lighter",
  "inherit", "initial", "unset", "revert", "revert-layer",
]);

/**
 * Colour keys require a dot: a bare word there is a CSS colour name
 * ("rebeccapurple", "transparent"), not a token. Wrapping one produced
 * `var(--token-#3b82f6)`, which the browser discards — the fill simply never
 * painted, with nothing in the console to say why.
 */
export function colorValue(value: string): string {
  return value.includes(".") && TOKEN_REF_SHAPE.test(value) ? tokenVar(value) : value;
}

/**
 * Scale keys must NOT require a dot — live schemas carry `"padding": "md"` and
 * `"gap": "lg"`, which resolve through compileTokens' name-only alias. They do
 * need the keyword guard and the shape test, so `"0"`, `"1rem"` and a literal
 * box-shadow like "0 1px 2px rgb(0 0 0 / 0.05)" pass through untouched instead
 * of becoming `var(--token-0)`.
 */
function scaleValue(value: string): string {
  return TOKEN_REF_SHAPE.test(value) && !CSS_KEYWORDS.has(value.toLowerCase())
    ? tokenVar(value)
    : value;
}

export function backgroundCss(bg: BackgroundT): string {
  switch (bg.type) {
    // ColorTokenRef is only `z.string().min(1)`, so raw colours reach these
    // branches too and get the same token-vs-raw treatment as the bare-string
    // background form below.
    case "solid":
      return colorValue(bg.value);
    case "gradient": {
      const angle = bg.angle ?? 135;
      return `linear-gradient(${angle}deg, ${colorValue(bg.from)} 0%, ${colorValue(bg.to)} 100%)`;
    }
    case "image": {
      const pos = bg.position ?? "center/cover";
      return `url("${bg.url}") ${pos}`;
    }
    case "pattern": {
      // v1: emit a CSS background-image stub that the runtime stylesheet
      // can pick up via [data-pattern] attribute. Color falls back to muted.
      const c = bg.color ? colorValue(bg.color) : "var(--token-color-muted-default)";
      return `radial-gradient(${c} 1px, transparent 1px) 0 0/16px 16px`;
    }
  }
}

/**
 * Per-node animation duration for `style.motion`.
 *
 * Emitted as the `--motion-duration` custom property that motion.css reads,
 * NOT as an `animation-duration` longhand: motion.css sets the whole
 * `animation` shorthand, which would reset a longhand declared on the same
 * element and drop the duration on the floor.
 *
 * It rides on resolveStyle rather than useMotion because every component that
 * spreads `useMotion(style?.motion)` also spreads `resolveStyle(style)` onto
 * that same element — so this reaches all ~100 of them without touching each
 * one's signature.
 */
function applyMotionDuration(slot: StyleSlotT, out: CSSProperties): void {
  if (slot.motion && slot.motion !== "none" && slot.motionDuration) {
    (out as Record<string, string>)["--motion-duration"] = slot.motionDuration;
  }
}

/** Copy raw sizing keys (width, height, min/max width + height) verbatim onto a
 * CSS object. These are literal CSS values ("240px", "50%", "auto"), not token refs. */
function applySizing(slot: StyleSlotT, out: CSSProperties): void {
  if (slot.width     !== undefined) out.width     = slot.width as CSSProperties["width"];
  if (slot.height    !== undefined) out.height    = slot.height as CSSProperties["height"];
  if (slot.minWidth  !== undefined) out.minWidth  = slot.minWidth as CSSProperties["minWidth"];
  if (slot.maxWidth  !== undefined) out.maxWidth  = slot.maxWidth as CSSProperties["maxWidth"];
  if (slot.minHeight !== undefined) out.minHeight = slot.minHeight as CSSProperties["minHeight"];
  if (slot.maxHeight !== undefined) out.maxHeight = slot.maxHeight as CSSProperties["maxHeight"];
}

export function resolveStyle(slot?: StyleSlotT): CSSProperties {
  if (!slot) return {};
  const out: CSSProperties = {};
  if (slot.padding)    out.padding      = scaleValue(slot.padding);
  if (slot.radius)     out.borderRadius = scaleValue(slot.radius);
  if (slot.shadow)     out.boxShadow    = scaleValue(slot.shadow);
  if (slot.background) {
    out.background = typeof slot.background === "string"
      ? colorValue(slot.background)
      : backgroundCss(slot.background);
  }
  applySizing(slot, out);
  applyMotionDuration(slot, out);
  return out;
}

/**
 * Same as `resolveStyle` but omits the `background` property. Use this on the
 * outer element when a sibling `<SurfaceBackground>` wrapper is rendering the
 * background, so the gradient/solid is not emitted twice.
 */
export function resolveStyleNoBackground(slot?: StyleSlotT): CSSProperties {
  if (!slot) return {};
  const out: CSSProperties = {};
  if (slot.padding) out.padding      = scaleValue(slot.padding);
  if (slot.radius)  out.borderRadius = scaleValue(slot.radius);
  if (slot.shadow)  out.boxShadow    = scaleValue(slot.shadow);
  applySizing(slot, out);
  applyMotionDuration(slot, out);
  return out;
}
