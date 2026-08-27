# Spec E Wave 2 — text-props rem sweep

Automated audit of `packages/library/src/components/**/*.tsx` for
hardcoded px values in text-related props (`fontSize`, `lineHeight`,
`letter-spacing`).

## Scan pattern
- Regex A: `fontSize:\s*['"][0-9]+px['"]` (inline React style)
- Regex B: `font-size:\s*[0-9]+px` (CSS strings)
- Regex C: `letter-spacing:\s*[0-9]+px`

## Findings — 2026-08-09

### Fixed inline (this sweep)
- `SideNav/SideNav.tsx` — 3 CSS rules using `font-size:14px` /
  `font-size:13px`. Converted to `0.875rem` / `0.8125rem` so the nav
  respects the user's browser font-size preference.

### Intentionally NOT rewritten
- **SVG `<text fontSize={...}>` in `Chart/*`, `Schematic`, `Gauge`.**
  These are SVG user-coord numbers, not CSS font-size. Converting to
  rem would break the geometry — the values are relative to the
  chart's viewBox, not the root font-size.

### Already rem-compliant (no change needed)
- `KeyboardShortcuts`, `CodeBlock`, `BulkActionBar`,
  `SavedViewsPicker`, `IllustratedEmpty`, `EmptyState`, `LoadingState`,
  `Link`, `SkipLink` — all use `rem` or `var(--typography-*)` tokens.

## Guard
No new hardcoded text-px values should be introduced. A follow-up
CI lint rule (`eslint-plugin-forge/no-text-px`) is TODO — for now the
sweep runs manually.
