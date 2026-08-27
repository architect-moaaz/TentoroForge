/**
 * Token System — bidirectional mapping between IR tokens and Tailwind classes.
 *
 * Tokens → Tailwind: used by the compiler to generate className strings.
 * Tailwind → Tokens: used by the round-trip parser to reverse-map edits.
 */

import type { SpacingToken, ColorToken, RadiusToken, TypographyToken, PaddingValue } from "./types.js";

// ---------------------------------------------------------------------------
// Spacing tokens → Tailwind
// ---------------------------------------------------------------------------

const SPACING_MAP: Record<SpacingToken, string> = {
  xs: "1",
  sm: "2",
  md: "4",
  lg: "6",
  xl: "8",
  "2xl": "12",
};

export function spacingToTailwind(token: SpacingToken): string {
  return SPACING_MAP[token] ?? "4";
}

export function gapClass(token: SpacingToken): string {
  return `gap-${spacingToTailwind(token)}`;
}

export function paddingClasses(value: PaddingValue): string {
  if (typeof value === "string") {
    return `p-${spacingToTailwind(value as SpacingToken)}`;
  }
  if ("x" in value || "y" in value) {
    const parts: string[] = [];
    if (value.x) parts.push(`px-${spacingToTailwind(value.x)}`);
    if (value.y) parts.push(`py-${spacingToTailwind(value.y)}`);
    return parts.join(" ");
  }
  if ("top" in value || "right" in value || "bottom" in value || "left" in value) {
    const parts: string[] = [];
    if (value.top) parts.push(`pt-${spacingToTailwind(value.top)}`);
    if (value.right) parts.push(`pr-${spacingToTailwind(value.right)}`);
    if (value.bottom) parts.push(`pb-${spacingToTailwind(value.bottom)}`);
    if (value.left) parts.push(`pl-${spacingToTailwind(value.left)}`);
    return parts.join(" ");
  }
  return "";
}

export function marginClasses(value: PaddingValue): string {
  // Same logic as padding but with m- prefix
  if (typeof value === "string") {
    return `m-${spacingToTailwind(value as SpacingToken)}`;
  }
  if ("x" in value || "y" in value) {
    const parts: string[] = [];
    if (value.x) parts.push(`mx-${spacingToTailwind(value.x)}`);
    if (value.y) parts.push(`my-${spacingToTailwind(value.y)}`);
    return parts.join(" ");
  }
  if ("top" in value || "right" in value || "bottom" in value || "left" in value) {
    const parts: string[] = [];
    if (value.top) parts.push(`mt-${spacingToTailwind(value.top)}`);
    if (value.right) parts.push(`mr-${spacingToTailwind(value.right)}`);
    if (value.bottom) parts.push(`mb-${spacingToTailwind(value.bottom)}`);
    if (value.left) parts.push(`ml-${spacingToTailwind(value.left)}`);
    return parts.join(" ");
  }
  return "";
}

// ---------------------------------------------------------------------------
// Color tokens → Tailwind
// ---------------------------------------------------------------------------

const TEXT_COLOR_MAP: Record<ColorToken, string> = {
  primary: "text-primary",
  secondary: "text-secondary-foreground",
  danger: "text-destructive",
  warning: "text-amber-600",
  success: "text-green-600",
  muted: "text-muted-foreground",
  default: "text-foreground",
  surface: "text-background",
  "surface-alt": "text-muted",
};

const BG_COLOR_MAP: Record<ColorToken, string> = {
  primary: "bg-primary",
  secondary: "bg-secondary",
  danger: "bg-destructive",
  warning: "bg-amber-100",
  success: "bg-green-100",
  muted: "bg-muted",
  default: "bg-background",
  surface: "bg-card",
  "surface-alt": "bg-muted/50",
};

export function textColorClass(token: ColorToken | string): string {
  return TEXT_COLOR_MAP[token as ColorToken] ?? `text-[${token}]`;
}

export function bgColorClass(token: ColorToken | string): string {
  return BG_COLOR_MAP[token as ColorToken] ?? `bg-[${token}]`;
}

// ---------------------------------------------------------------------------
// Radius tokens → Tailwind
// ---------------------------------------------------------------------------

const RADIUS_MAP: Record<RadiusToken, string> = {
  none: "rounded-none",
  sm: "rounded-sm",
  md: "rounded-md",
  lg: "rounded-lg",
  full: "rounded-full",
};

export function radiusClass(token: RadiusToken): string {
  return RADIUS_MAP[token] ?? "rounded-md";
}

// ---------------------------------------------------------------------------
// Typography tokens → Tailwind + HTML element
// ---------------------------------------------------------------------------

export interface TypographyResolved {
  element: string;
  classes: string;
}

const TYPOGRAPHY_MAP: Record<TypographyToken, TypographyResolved> = {
  "heading-1": { element: "h1", classes: "text-2xl font-bold tracking-tight" },
  "heading-2": { element: "h2", classes: "text-xl font-semibold tracking-tight" },
  "heading-3": { element: "h3", classes: "text-lg font-semibold" },
  body: { element: "p", classes: "text-sm" },
  "body-sm": { element: "p", classes: "text-sm text-muted-foreground" },
  caption: { element: "span", classes: "text-xs text-muted-foreground" },
  overline: { element: "span", classes: "text-xs font-medium uppercase tracking-wider text-muted-foreground" },
};

export function resolveTypography(token: TypographyToken): TypographyResolved {
  return TYPOGRAPHY_MAP[token] ?? TYPOGRAPHY_MAP.body;
}

// ---------------------------------------------------------------------------
// Alignment / Justify → Tailwind
// ---------------------------------------------------------------------------

const ALIGN_MAP: Record<string, string> = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  stretch: "items-stretch",
};

const JUSTIFY_MAP: Record<string, string> = {
  start: "justify-start",
  center: "justify-center",
  end: "justify-end",
  between: "justify-between",
  around: "justify-around",
};

export function alignClass(value: string): string {
  return ALIGN_MAP[value] ?? "";
}

export function justifyClass(value: string): string {
  return JUSTIFY_MAP[value] ?? "";
}

// ---------------------------------------------------------------------------
// Size helpers
// ---------------------------------------------------------------------------

const ICON_SIZE_MAP: Record<string, string> = {
  xs: "h-3 w-3",
  sm: "h-4 w-4",
  md: "h-5 w-5",
  lg: "h-6 w-6",
  xl: "h-8 w-8",
};

export function iconSizeClass(size: string): string {
  return ICON_SIZE_MAP[size] ?? ICON_SIZE_MAP.md;
}

const AVATAR_SIZE_MAP: Record<string, string> = {
  xs: "h-5 w-5",
  sm: "h-6 w-6",
  md: "h-8 w-8",
  lg: "h-10 w-10",
  xl: "h-14 w-14",
};

export function avatarSizeClass(size: string): string {
  return AVATAR_SIZE_MAP[size] ?? AVATAR_SIZE_MAP.md;
}

// ---------------------------------------------------------------------------
// Responsive value → Tailwind
// ---------------------------------------------------------------------------

const BREAKPOINT_PREFIX: Record<string, string> = {
  default: "",
  sm: "sm:",
  md: "md:",
  lg: "lg:",
  xl: "xl:",
};

export function responsiveClasses<T>(
  value: T | Record<string, T>,
  toClass: (val: T, prefix: string) => string,
): string {
  if (typeof value !== "object" || value === null) {
    return toClass(value as T, "");
  }
  const record = value as Record<string, T>;
  return Object.entries(record)
    .map(([bp, val]) => {
      const prefix = BREAKPOINT_PREFIX[bp] ?? "";
      return toClass(val, prefix);
    })
    .filter(Boolean)
    .join(" ");
}

// ---------------------------------------------------------------------------
// Reverse mapping: Tailwind → Tokens (for round-trip parser)
// ---------------------------------------------------------------------------

const REVERSE_SPACING: Record<string, SpacingToken> = {};
for (const [token, tw] of Object.entries(SPACING_MAP)) {
  REVERSE_SPACING[tw] = token as SpacingToken;
}

const REVERSE_RADIUS: Record<string, RadiusToken> = {};
for (const [token, tw] of Object.entries(RADIUS_MAP)) {
  REVERSE_RADIUS[tw] = token as RadiusToken;
}

export function tailwindToSpacing(twValue: string): SpacingToken | undefined {
  return REVERSE_SPACING[twValue];
}

export function tailwindToRadius(twClass: string): RadiusToken | undefined {
  return REVERSE_RADIUS[twClass];
}

// ---------------------------------------------------------------------------
// Utility: build class string from array, filtering falsy values
// ---------------------------------------------------------------------------

export function buildClasses(classes: (string | false | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}
