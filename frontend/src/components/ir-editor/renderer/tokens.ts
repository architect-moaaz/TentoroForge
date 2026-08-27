/**
 * Token-to-Tailwind mapping for runtime rendering.
 *
 * Mirrors packages/ir/src/tokens.ts but returns class strings
 * for direct use in className props.
 */

const SPACING: Record<string, string> = {
  xs: "1", sm: "2", md: "4", lg: "6", xl: "8", "2xl": "12",
};

export function gapClass(token: string | undefined): string {
  if (!token) return "";
  return `gap-${SPACING[token] ?? token}`;
}

export function paddingClasses(
  value: string | { x?: string; y?: string; top?: string; right?: string; bottom?: string; left?: string } | undefined,
): string {
  if (!value) return "";
  if (typeof value === "string") return `p-${SPACING[value] ?? value}`;
  const parts: string[] = [];
  if (value.x) parts.push(`px-${SPACING[value.x] ?? value.x}`);
  if (value.y) parts.push(`py-${SPACING[value.y] ?? value.y}`);
  if (value.top) parts.push(`pt-${SPACING[value.top] ?? value.top}`);
  if (value.right) parts.push(`pr-${SPACING[value.right] ?? value.right}`);
  if (value.bottom) parts.push(`pb-${SPACING[value.bottom] ?? value.bottom}`);
  if (value.left) parts.push(`pl-${SPACING[value.left] ?? value.left}`);
  return parts.join(" ");
}

const COLOR_MAP: Record<string, string> = {
  primary: "blue-600", secondary: "gray-600", danger: "red-600",
  warning: "amber-500", success: "green-600", muted: "gray-500",
  default: "gray-900", surface: "white",
};

export function textColorClass(token: string | undefined): string {
  if (!token) return "";
  return `text-${COLOR_MAP[token] ?? token}`;
}

export function bgColorClass(token: string | undefined): string {
  if (!token) return "";
  return `bg-${COLOR_MAP[token] ?? token}`;
}

const RADIUS_MAP: Record<string, string> = {
  none: "rounded-none", sm: "rounded-sm", md: "rounded-md",
  lg: "rounded-lg", full: "rounded-full",
};

export function radiusClass(token: string | undefined): string {
  if (!token) return "";
  return RADIUS_MAP[token] ?? `rounded-${token}`;
}

const TYPOGRAPHY: Record<string, { element: string; classes: string }> = {
  "heading-1": { element: "h1", classes: "text-3xl font-bold tracking-tight" },
  "heading-2": { element: "h2", classes: "text-2xl font-semibold tracking-tight" },
  "heading-3": { element: "h3", classes: "text-lg font-semibold" },
  body: { element: "p", classes: "text-base" },
  "body-sm": { element: "p", classes: "text-sm" },
  caption: { element: "span", classes: "text-xs text-gray-500" },
  overline: { element: "span", classes: "text-xs font-semibold uppercase tracking-wider text-gray-500" },
};

export function resolveTypography(token: string | undefined): { element: string; classes: string } {
  if (!token) return { element: "p", classes: "text-base" };
  return TYPOGRAPHY[token] ?? { element: "p", classes: "text-base" };
}

export function alignClass(value: string | undefined): string {
  if (!value) return "";
  const map: Record<string, string> = {
    start: "items-start", center: "items-center",
    end: "items-end", stretch: "items-stretch",
  };
  return map[value] ?? "";
}

export function justifyClass(value: string | undefined): string {
  if (!value) return "";
  const map: Record<string, string> = {
    start: "justify-start", center: "justify-center",
    end: "justify-end", between: "justify-between", around: "justify-around",
  };
  return map[value] ?? "";
}

export function iconSizeClass(size: string | undefined): string {
  const map: Record<string, string> = {
    xs: "h-3 w-3", sm: "h-4 w-4", md: "h-5 w-5", lg: "h-6 w-6", xl: "h-8 w-8",
  };
  return map[size ?? "md"] ?? "h-5 w-5";
}

export function avatarSizeClass(size: string | undefined): string {
  const map: Record<string, string> = {
    xs: "h-5 w-5", sm: "h-6 w-6", md: "h-8 w-8", lg: "h-10 w-10", xl: "h-14 w-14",
  };
  return map[size ?? "md"] ?? "h-8 w-8";
}

export function widthClass(width: string | undefined): string {
  if (!width) return "";
  const map: Record<string, string> = { full: "w-full", auto: "w-auto", screen: "w-screen" };
  return map[width] ?? `w-[${width}]`;
}

export function heightClass(height: string | undefined): string {
  if (!height) return "";
  const map: Record<string, string> = { full: "h-full", auto: "h-auto", screen: "h-screen" };
  return map[height] ?? `h-[${height}]`;
}

export function buildClasses(...classes: (string | undefined | false | null)[]): string {
  return classes.filter(Boolean).join(" ");
}
