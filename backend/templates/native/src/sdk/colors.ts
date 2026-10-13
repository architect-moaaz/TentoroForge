// The app SDK (native) — colour tokens, without React.
//
// THE TOKENS ARE THE WEB'S (the library's `token-contract.json`: background,
// foreground, card, muted, primary, accent, destructive, success, warning,
// info, each with its `-foreground` and `-subtle` pairs), in camelCase because
// they are object keys here: `cardForeground`, `accentSubtle`.
// `theme.generated.ts` (projected from the Blueprint's design system) gives
// the ones the app overrides; the rest are these defaults, so a screen can use
// any token whatever the Blueprint said.
//
// A value may be what the web projects — an HSL triplet `"243 75% 59%"` — or
// anything react-native takes (`#5048e5`, `rgb(...)`). `toColor` makes the
// first into the second, which react-native does not read.
//
// PURE — no react-native import.

/** The light defaults, as the web's `theme.css` has them (HSL triplets). */
export const DEFAULT_COLORS = {
  background: "210 20% 98%",
  foreground: "221 39% 11%",
  card: "0 0% 100%",
  cardForeground: "221 39% 11%",
  popover: "0 0% 100%",
  popoverForeground: "221 39% 11%",
  muted: "226 100% 97%",
  mutedForeground: "220 9% 46%",
  border: "220 13% 91%",
  input: "220 13% 91%",
  ring: "243 75% 59%",
  primary: "243 75% 59%",
  primaryForeground: "0 0% 100%",
  secondary: "220 14% 96%",
  secondaryForeground: "222 84% 5%",
  accent: "38 92% 50%",
  accentForeground: "222 84% 5%",
  accentSubtle: "48 100% 96%",
  accentSubtleForeground: "31 92% 30%",
  inverse: "222 47% 11%",
  inverseForeground: "210 20% 98%",
  destructive: "0 74% 42%",
  destructiveForeground: "0 0% 100%",
  destructiveSubtle: "0 86% 97%",
  destructiveSubtleForeground: "0 74% 32%",
  success: "142 71% 29%",
  successForeground: "0 0% 100%",
  successSubtle: "141 79% 93%",
  successSubtleForeground: "142 71% 22%",
  warning: "31 92% 37%",
  warningForeground: "0 0% 100%",
  warningSubtle: "48 96% 89%",
  warningSubtleForeground: "31 92% 30%",
  info: "201 96% 32%",
  infoForeground: "0 0% 100%",
  infoSubtle: "204 94% 94%",
  infoSubtleForeground: "201 96% 26%",
} as const;

export type ColorToken = keyof typeof DEFAULT_COLORS;

/** `"243 75% 59%"` -> `"#5048e5"`; anything else is returned as it is. */
export function toColor(value: string): string {
  const m = /^\s*(-?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)%\s+(\d+(?:\.\d+)?)%\s*$/.exec(value);
  if (!m) return value;
  const h = ((Number(m[1]) % 360) + 360) % 360;
  const s = Math.min(100, Number(m[2])) / 100;
  const l = Math.min(100, Number(m[3])) / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const hex = (x: number) => Math.round(x * 255).toString(16).padStart(2, "0");
  return `#${hex(f(0))}${hex(f(8))}${hex(f(4))}`;
}

/** The full palette: the defaults, with what the app overrides on top. An
 *  override that is not a string (or not a known token) is ignored. */
export function resolveColors(overrides: Readonly<Record<string, string | undefined>> | undefined): Record<ColorToken, string> {
  const out = {} as Record<ColorToken, string>;
  for (const token of Object.keys(DEFAULT_COLORS) as ColorToken[]) {
    const o = overrides?.[token];
    out[token] = toColor(typeof o === "string" && o.trim() ? o : DEFAULT_COLORS[token]);
  }
  return out;
}

/** `#rrggbb` + 0.4 -> `rgba(r,g,b,0.4)`; a colour that is not 6-digit hex is returned as it is. */
export function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}
