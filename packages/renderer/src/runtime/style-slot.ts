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

  if (slot.padding)    (css as any).padding      = scaleValue(slot.padding);
  if (slot.radius)     (css as any).borderRadius = scaleValue(slot.radius);
  if (slot.shadow)     (css as any).boxShadow    = scaleValue(slot.shadow);
  // Background may be either the structured BackgroundT discriminated-union
  // form or a bare string — the schema accepts both. The bare-string form is
  // NOT always a token ref: schemas in the wild (and the editor's Background
  // control) also carry raw CSS fills like "#3b82f6", "hsl(210 20% 98%)",
  // "linear-gradient(to bottom, white, black)" and "url(data:image/png;…)".
  // Blindly token-wrapping those produced `var(--token-#3b82f6)` /
  // `var(--token-linear-gradient(to bottom, white, black))`, which the browser
  // drops on the floor — the fill silently never painted. Resolve per value.
  if (slot.background) {
    (css as any).background = typeof slot.background === "string"
      ? colorValue(slot.background)
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

  // Sizing — always emitted raw, no token lookup at all. Historically this also
  // served to OVERRIDE the token-wrapped width/height that tokens.resolveStyle
  // emitted onto the same element (structural nodes spread applyStyleSlot after
  // it); that resolver now discriminates too, so this is no longer papering over
  // a broken sibling. minWidth/maxWidth/minHeight/maxHeight aren't in that
  // resolver at all, so they only come from here.
  if (slot.width     !== undefined) (css as any).width     = slot.width;
  if (slot.height    !== undefined) (css as any).height    = slot.height;
  if (slot.minWidth  !== undefined) (css as any).minWidth  = slot.minWidth;
  if (slot.maxWidth  !== undefined) (css as any).maxWidth  = slot.maxWidth;
  if (slot.minHeight !== undefined) (css as any).minHeight = slot.minHeight;
  if (slot.maxHeight !== undefined) (css as any).maxHeight = slot.maxHeight;

  // Motion duration rides along as an inline custom property rather than an
  // `animation-duration` declaration: motion.css owns the full `animation`
  // shorthand, and a shorthand always wins over a longhand set earlier on the
  // same element's style attribute — the longhand would be overwritten and the
  // duration lost. `--motion-duration` is the fallback slot every [data-motion]
  // rule in motion.css reads. Gated on an actual motion because a duration with
  // nothing to animate is dead weight in the DOM.
  if (slot.motion && slot.motion !== "none" && slot.motionDuration) {
    (css as any)["--motion-duration"] = slot.motionDuration;
  }

  if (Object.keys(css).length > 0) out.style = css;
  if (slot.motion && slot.motion !== "none") out["data-motion"] = slot.motion;

  return out;
}

function tokenVar(ref: string): string {
  // "tokens.spacing.semantic.section" → "var(--token-spacing-semantic-section)"
  // "spacing.4" → "var(--token-spacing-4)"
  return `var(--token-${ref.replace(/^tokens\./, "").replace(/\./g, "-")})`;
}

/**
 * Shape a design-token reference has: dot-separated bare identifiers, e.g.
 * "color.primary.500", "tokens.color.surface.0", "md". Nothing that starts with
 * a digit, "#", "-" or "." can match, and neither can anything containing a
 * space, comma, slash or parenthesis — which excludes every raw CSS value of
 * the forms these style keys actually carry ("240px", "50%", "#3b82f6",
 * "rgb(59 130 246)", "0 1px 2px rgb(0 0 0 / 0.05)", "linear-gradient(…)").
 */
const TOKEN_REF_SHAPE = /^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*$/;

/**
 * Bare words that are CSS values, not token names. Without this list
 * `width: "auto"` and `fontWeight: "bold"` match the identifier shape and get
 * wrapped into `var(--token-auto)`, which resolves to nothing.
 */
const CSS_KEYWORDS = new Set([
  "auto", "none", "normal", "bold", "bolder", "lighter",
  "inherit", "initial", "unset", "revert", "revert-layer",
]);

/**
 * Token-vs-raw for COLOUR-valued keys (background, color, borderColor).
 *
 * Here a bare word is overwhelmingly a CSS colour name — "rebeccapurple",
 * "white", "transparent" — so a dot is REQUIRED for the value to count as a
 * token. There are no dotless colour tokens in any schema in this repo, and the
 * editor's colour control needs bare names to survive as literals.
 *
 * Exported because that control has to make the same call to decide between a
 * token chip and a colour swatch; a second copy of this rule would drift and
 * the panel would disagree with what the canvas actually paints.
 */
export function isColorTokenRef(value: string): boolean {
  return value.includes(".") && TOKEN_REF_SHAPE.test(value);
}

/**
 * Token-vs-raw for SCALE-valued keys (spacing, sizing, radius, shadow, type).
 *
 * These CANNOT require a dot: live schemas carry `"gap": "md"`, `"gap": "lg"`
 * and `"padding": "md"`, which resolve today through compileTokens' legacy
 * name-only alias (`--token-md`). Requiring a dot would silently drop every one
 * of them. The same schemas also carry `"width": "788px"`, `"width": "30%"`,
 * `"lineHeight": "1.5"` and `"letterSpacing": "-0.01em"` — all of which fail
 * the identifier shape and so pass through raw, where before they became
 * `var(--token-788px)` and painted nothing.
 */
export function isScaleTokenRef(value: string): boolean {
  return TOKEN_REF_SHAPE.test(value) && !CSS_KEYWORDS.has(value.toLowerCase());
}

/** Compile a colour-key value: token ref → CSS var, anything else verbatim. */
function colorValue(value: string): string {
  return isColorTokenRef(value) ? tokenVar(value) : value;
}

/** Compile a scale-key value: token ref → CSS var, anything else verbatim. */
function scaleValue(value: string): string {
  return isScaleTokenRef(value) ? tokenVar(value) : value;
}

function backgroundCss(bg: BackgroundT): string {
  switch (bg.type) {
    // `value`/`from`/`to`/`color` are typed as ColorTokenRef but that is only
    // `z.string().min(1)`, so raw colours reach these branches too — resolve
    // them the same way the bare-string form is resolved.
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
      const c = bg.color ? colorValue(bg.color) : "var(--token-color-muted-default)";
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
