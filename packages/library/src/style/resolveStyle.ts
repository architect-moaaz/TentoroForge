// packages/library/src/style/resolveStyle.ts
import type { CSSProperties } from "react";
import type { StyleSlotT, BackgroundT } from "@tentoroforge/schema";

function tokenVar(ref: string): string {
  // tokens.color.primary.500 → var(--token-color-primary-500)
  return `var(--token-${ref.replace(/^tokens\./, "").replace(/\./g, "-")})`;
}

export function backgroundCss(bg: BackgroundT): string {
  switch (bg.type) {
    case "solid":
      return tokenVar(bg.value);
    case "gradient": {
      const angle = bg.angle ?? 135;
      return `linear-gradient(${angle}deg, ${tokenVar(bg.from)} 0%, ${tokenVar(bg.to)} 100%)`;
    }
    case "image": {
      const pos = bg.position ?? "center/cover";
      return `url("${bg.url}") ${pos}`;
    }
    case "pattern": {
      // v1: emit a CSS background-image stub that the runtime stylesheet
      // can pick up via [data-pattern] attribute. Color falls back to muted.
      const c = bg.color ? tokenVar(bg.color) : "var(--token-color-muted-default)";
      return `radial-gradient(${c} 1px, transparent 1px) 0 0/16px 16px`;
    }
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
  if (slot.padding)    out.padding      = tokenVar(slot.padding);
  if (slot.radius)     out.borderRadius = tokenVar(slot.radius);
  if (slot.shadow)     out.boxShadow    = tokenVar(slot.shadow);
  if (slot.background) {
    out.background = typeof slot.background === "string"
      ? tokenVar(slot.background)
      : backgroundCss(slot.background);
  }
  applySizing(slot, out);
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
  if (slot.padding) out.padding      = tokenVar(slot.padding);
  if (slot.radius)  out.borderRadius = tokenVar(slot.radius);
  if (slot.shadow)  out.boxShadow    = tokenVar(slot.shadow);
  applySizing(slot, out);
  return out;
}
