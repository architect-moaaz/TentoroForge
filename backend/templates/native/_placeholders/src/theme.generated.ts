// PLACEHOLDER of the generated `src/theme.generated.ts` — not copied into apps.
// The projector writes the Blueprint's design tokens here (see README.md,
// "The generated files"). Plain data, no imports; `theme.ts` fills whatever is
// missing from the web's own defaults.

/** Overrides of the light palette, by camelCase token (`primary`, `accentSubtle`,
 *  `cardForeground`, ...). HSL triplets ("243 75% 59%") as the web projects
 *  them, or any colour react-native reads (#5048e5). Unknown names are ignored. */
export const colors: Record<string, string> = {
  primary: "243 75% 59%",
};

/** The corner radius of a control, in points (the web's `--radius`). */
export const radius: number = 8;

/** The design's measures (see `services/blueprint/native_tokens.py`): corner radii, the spacing scale, the page
 *  margin, three shadows, the type scale (base size over 16) and the hairline. */
export const radii = { sm: 8, md: 12, lg: 16 } as const;
export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const pagePadding: number = 16;
export const shadows = {
  1: { shadowColor: "#0f172a", shadowOpacity: 0.06, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 1 },
  2: { shadowColor: "#0f172a", shadowOpacity: 0.1, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 3 },
  3: { shadowColor: "#0f172a", shadowOpacity: 0.16, shadowRadius: 20, shadowOffset: { width: 0, height: 8 }, elevation: 8 },
};
export const typeScale: number = 1;
export const borderWidth: number = 1;
/** How headings look: weight, colour (a tone) and a page title's size (null = the kit's). */
export const heading: { weight: "regular" | "medium" | "semibold" | "bold"; tone: "default" | "primary" | "accent"; titleSize: number | null } = { weight: "bold", tone: "default", titleSize: null };

/** Typefaces, only if the app loads them (`fonts.generated.ts`): one family name per weight (`Inter_700Bold`),
 *  the system font otherwise. */
export const fonts: {
  body?: { regular: string; medium?: string; semibold?: string; bold?: string };
  heading?: { regular: string; medium?: string; semibold?: string; bold?: string };
} = {};
