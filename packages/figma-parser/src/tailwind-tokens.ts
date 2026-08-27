export type StyleProps = Record<string, string>;

export type TokenResult = {
  style: StyleProps;
  unmapped: string[];
};

// Color scale steps
const STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];

// Color group → token namespace mapping
const COLOR_NAMESPACES: Record<string, string> = {
  blue: "primary",
  gray: "neutral",
  red: "danger",
  green: "success",
  yellow: "warning",
};

// Build the static bg-* lookup table
function buildColorMap(prefix: "bg" | "text"): Record<string, string> {
  const map: Record<string, string> = {};
  for (const [color, ns] of Object.entries(COLOR_NAMESPACES)) {
    for (const step of STEPS) {
      map[`${prefix}-${color}-${step}`] = `${ns}.${step}`;
    }
  }
  // Special values
  map[`${prefix}-white`] = "neutral.0";
  map[`${prefix}-black`] = "neutral.900";
  return map;
}

const BG_MAP = buildColorMap("bg");
const TEXT_COLOR_MAP = buildColorMap("text");

// Typography size map (text-* that map to font sizes)
const TEXT_SIZE_MAP: Record<string, string> = {
  "text-xs": "typography.xs",
  "text-sm": "typography.sm",
  "text-base": "typography.base",
  "text-lg": "typography.lg",
  "text-xl": "typography.xl",
  "text-2xl": "typography.2xl",
};

// Radius map
const ROUNDED_MAP: Record<string, string> = {
  "rounded-sm": "radii.sm",
  "rounded-md": "radii.md",
  "rounded-lg": "radii.lg",
  "rounded-xl": "radii.xl",
  "rounded-full": "radii.full",
};

// Shadow map
const SHADOW_MAP: Record<string, string> = {
  "shadow-sm": "shadows.sm",
  "shadow-md": "shadows.md",
  "shadow-lg": "shadows.lg",
};

// Build padding map p-0..p-16
function buildPaddingMap(): Record<string, string> {
  const map: Record<string, string> = {};
  for (let i = 0; i <= 16; i++) {
    map[`p-${i}`] = `spacing.${i}`;
  }
  return map;
}

const PADDING_MAP = buildPaddingMap();

/**
 * Parse a Tailwind className string and map classes to design tokens.
 * Known classes are mapped to a style object; unknown classes go in unmapped[].
 */
export function tailwindToTokens(className: string): TokenResult {
  const style: StyleProps = {};
  const unmapped: string[] = [];

  const classes = className.split(/\s+/).filter(Boolean);

  for (const cls of classes) {
    if (BG_MAP[cls] !== undefined) {
      style["background"] = BG_MAP[cls];
    } else if (TEXT_SIZE_MAP[cls] !== undefined) {
      style["fontSize"] = TEXT_SIZE_MAP[cls];
    } else if (TEXT_COLOR_MAP[cls] !== undefined) {
      // text-* color (only if not a size class)
      style["color"] = TEXT_COLOR_MAP[cls];
    } else if (PADDING_MAP[cls] !== undefined) {
      style["padding"] = PADDING_MAP[cls];
    } else if (ROUNDED_MAP[cls] !== undefined) {
      style["borderRadius"] = ROUNDED_MAP[cls];
    } else if (SHADOW_MAP[cls] !== undefined) {
      style["boxShadow"] = SHADOW_MAP[cls];
    } else {
      unmapped.push(cls);
    }
  }

  return { style, unmapped };
}
