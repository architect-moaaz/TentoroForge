// packages/renderer/src/runtime/style-slot.ts
import type { CSSProperties } from "react";
import type { StyleSlotT, BackgroundT } from "@tentoroforge/schema";

/**
 * Renderer-side resolution of a StyleSlotT node. Inlined here to avoid
 * the renderer depending on @tentoroforge/library at runtime — structural
 * types (Stack, Row, Box, …) render without the component library.
 *
 * Returns props to spread onto a wrapper element:
 *   { style?: CSSProperties, "data-motion"?: string }
 */
export function applyStyleSlot(slot?: StyleSlotT): {
  style?: CSSProperties;
  "data-motion"?: string;
} {
  if (!slot) return {};
  const out: { style?: CSSProperties; "data-motion"?: string } = {};
  const css: CSSProperties = {};

  if (slot.padding)    (css as any).padding      = tokenVar(slot.padding);
  if (slot.radius)     (css as any).borderRadius = tokenVar(slot.radius);
  if (slot.shadow)     (css as any).boxShadow    = tokenVar(slot.shadow);
  // Background may be either the structured BackgroundT discriminated-union
  // form or a bare token-string (`tokens.color.surface.0`) — the schema now
  // accepts both. Treat strings as solid-fill token references.
  if (slot.background) {
    (css as any).background = typeof slot.background === "string"
      ? tokenVar(slot.background)
      : backgroundCss(slot.background as BackgroundT);
  }

  if (slot.position) {
    (css as any).position = slot.position.type;
    if (slot.position.top     !== undefined) (css as any).top    = slot.position.top;
    if (slot.position.right   !== undefined) (css as any).right  = slot.position.right;
    if (slot.position.bottom  !== undefined) (css as any).bottom = slot.position.bottom;
    if (slot.position.left    !== undefined) (css as any).left   = slot.position.left;
    if (slot.position.zIndex  !== undefined) (css as any).zIndex = slot.position.zIndex;
  }

  // Sizing — emit raw ("240px"/"50%"/"auto"), NOT token-wrapped. Structural
  // nodes spread applyStyleSlot AFTER tokens.resolveStyle, so these override the
  // (token-wrapped, therefore broken for raw values) width/height that resolver
  // would emit. minWidth/maxWidth/minHeight/maxHeight aren't in that resolver at
  // all, so they only come from here.
  if (slot.width     !== undefined) (css as any).width     = slot.width;
  if (slot.height    !== undefined) (css as any).height    = slot.height;
  if (slot.minWidth  !== undefined) (css as any).minWidth  = slot.minWidth;
  if (slot.maxWidth  !== undefined) (css as any).maxWidth  = slot.maxWidth;
  if (slot.minHeight !== undefined) (css as any).minHeight = slot.minHeight;
  if (slot.maxHeight !== undefined) (css as any).maxHeight = slot.maxHeight;

  if (Object.keys(css).length > 0) out.style = css;
  if (slot.motion && slot.motion !== "none") out["data-motion"] = slot.motion;

  return out;
}

function tokenVar(ref: string): string {
  // "tokens.spacing.semantic.section" → "var(--token-spacing-semantic-section)"
  // "spacing.4" → "var(--token-spacing-4)"
  return `var(--token-${ref.replace(/^tokens\./, "").replace(/\./g, "-")})`;
}

function backgroundCss(bg: BackgroundT): string {
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
      const c = bg.color ? tokenVar(bg.color) : "var(--token-color-muted-default)";
      return `radial-gradient(${c} 1px, transparent 1px) 0 0/16px 16px`;
    }
  }
}

/**
 * Pick schema-supplied `data-*` attribute props from a node's raw props so
 * layout nodes (Grid/Row/Stack) can spread them onto their root element.
 * Schemas mark nodes for app-level CSS/JS hooks (e.g. data-dashboard-toolbar);
 * dropping them forces app CSS into fragile :has() selectors.
 */
export function dataAttrProps(props: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(props)) {
    if (k.startsWith("data-")) out[k] = props[k];
  }
  return out;
}
