# Design System Overhaul — Wave 2: Token System Expansion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Expand the token system from "colors + a few spacing/radius/shadow values" to "colors + density + elevation + radius scale + typography pairing + motion" — and update every library component to read the new tokens. After Wave 2, the token system can drive layout (not just color), unlocking Wave 3 stylistic registers.

**Architecture:** Extend `packages/library/src/theme/default-tokens.ts` with 6 new groups; extend `packages/renderer/src/runtime/tokens.ts` `compileTokens` to emit CSS variables for all new groups; add a `tokens-context.tsx` React provider; refactor 30+ components in 4 batches to read the new tokens. All changes preserve today's appearance — defaults match exactly what shipped before. Phase 0's visual regression suite catches drift.

**Tech Stack:** TypeScript / React 19 / Tailwind 3 / Zod / Playwright (visual regression). Predecessors from Wave 1: hierarchy props, CVA template, visual regression suite, schema migration corpus.

**Spec:** `docs/superpowers/specs/2026-05-08-design-system-overhaul-design.md` § Phase 2.

---

## File structure

### New files

- `packages/library/src/theme/token-types.ts` — TS types for the expanded shape
- `packages/library/src/theme/tokens-context.tsx` — React provider + `useTokens()` hook
- `packages/library/src/theme/__tests__/compileTokens.test.ts` — token compiler tests

### Modified files

- `packages/library/src/theme/default-tokens.ts` — add density/elevation/radius.scale/typography.display/body/numeric/scale/motion groups
- `packages/renderer/src/runtime/tokens.ts` — `compileTokens` emits CSS vars for new groups
- 30+ library component files (`packages/library/src/components/<X>/<X>.tsx`) — read new tokens
- `backend/services/schema_prompt.py` — token-paths block surfaces new groups
- `frontend/src/components/schema-editor/PropertiesPanel/Style.tsx` — Style tab gains selectors for new groups
- `apps/visual-regression/tests/components.spec.ts-snapshots/` — re-baselined for affected components

---

## Token shape after Wave 2

```ts
// New groups added; existing groups unchanged.
{
  color:      { ...today, no changes },
  spacing:    { ...today, no changes },
  shadow:     { ...today, no changes },
  radius: {
    sm, md, lg, xl, full,                      // ...today (unchanged)
    scale: "sharp" | "soft" | "round",         // NEW — drives default radius family
  },
  typography: {
    font: { body, heading },                   // ...today (preserved for back-compat)
    weight: { body, heading },                 //  ditto
    scale: { h1, h2, h3, body, caption },      //  ditto

    display: { family, weight: 700 },          // NEW — headlines, hero text
    bodyText: { family, weight: 400, lineHeight: 1.5 },  // NEW — paragraphs, labels
    numeric:  { family, weight: 500, tabular: true },    // NEW — metric values
    scaleMode: "tight" | "balanced" | "dramatic",        // NEW — H1→H6 size jump
  },

  density:    "compact" | "comfortable" | "spacious",     // NEW — drives gaps
  elevation:  "flat" | "bordered" | "layered" | "floating",  // NEW
  motion:     "none" | "subtle" | "expressive",           // NEW
}
```

NOTE: existing top-level `radius` keys (sm, md, lg, xl, full) and `typography.font/weight/scale` are preserved unchanged. New groups are additive. The default for every new group matches today's appearance:
- `radius.scale` defaults to `"soft"` (today's `md = 0.5rem` baseline)
- `typography.display.family` defaults to today's `typography.font.heading`
- `typography.bodyText.family` defaults to today's `typography.font.body`
- `typography.numeric.family` defaults to today's `typography.font.body` + `tabular: false`
- `typography.scaleMode` defaults to `"balanced"` (today's scale)
- `density` defaults to `"comfortable"` (today's gaps)
- `elevation` defaults to `"layered"` (today's `shadow-sm` Card baseline)
- `motion` defaults to `"subtle"` (today's framer-motion fade defaults)

---

## Task 1: Token type definitions

**Files:**
- Create: `packages/library/src/theme/token-types.ts`

- [ ] **Step 1: Write the type file**

```ts
// packages/library/src/theme/token-types.ts
/**
 * Type definitions for the expanded token system.
 *
 * Defaults match today's appearance — adding a new group with its default
 * value is a no-op visually. Wave 3 stylistic registers override these
 * defaults to produce different design "personalities" (Workday/Linear/etc).
 */

export type RadiusScale = "sharp" | "soft" | "round";
export type Density = "compact" | "comfortable" | "spacious";
export type Elevation = "flat" | "bordered" | "layered" | "floating";
export type Motion = "none" | "subtle" | "expressive";
export type ScaleMode = "tight" | "balanced" | "dramatic";

export interface TypographyDisplay {
  family: string;
  weight: number;
}
export interface TypographyBodyText {
  family: string;
  weight: number;
  lineHeight: number;
}
export interface TypographyNumeric {
  family: string;
  weight: number;
  tabular: boolean;
}

/** Type guard / runtime accessor for the new groups. */
export interface ExpandedTokens {
  radius:     { scale: RadiusScale };
  typography: {
    display: TypographyDisplay;
    bodyText: TypographyBodyText;
    numeric: TypographyNumeric;
    scaleMode: ScaleMode;
  };
  density: Density;
  elevation: Elevation;
  motion: Motion;
}
```

- [ ] **Step 2: Verify**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -20 || true
```

- [ ] **Step 3: Commit**

```bash
git add packages/library/src/theme/token-types.ts
git commit -m "feat(tokens): type definitions for density/elevation/radius.scale/typography.display+body+numeric/scaleMode/motion"
```

---

## Task 2: Default tokens extended

**Files:**
- Modify: `packages/library/src/theme/default-tokens.ts`

- [ ] **Step 1: Read current file**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/packages/library/src/theme/default-tokens.ts | head -100
```

- [ ] **Step 2: Append new groups**

Add new top-level groups to `defaultTokens` (preserving all existing keys exactly):

```ts
// Inside defaultTokens object (additive, after existing groups):

  // ── radius.scale ────────────────────────────────────────────
  // Existing radius { sm, md, lg, xl, full } preserved above.
  // `scale` chooses the family used by components that read this token.
  // Default = "soft" maps to today's `md = 0.5rem` baseline.

  // (NOTE: this goes inside `radius` — extending the existing object.
  // The implementer should locate `radius:` in the file and add scale: alongside sm/md/lg.)

  // ── typography (additive) ───────────────────────────────────
  // Existing typography.font / weight / scale preserved.
  // New keys for the expanded system:

  // typography.display, .bodyText, .numeric, .scaleMode are new keys
  // added inside the existing typography object.

  density: "comfortable" as const,
  elevation: "layered" as const,
  motion: "subtle" as const,
```

NOTE for implementer: the actual edits are:
1. Add `scale: "soft" as const` inside `radius: { ... }`
2. Inside `typography: { ... }`, add:
   ```ts
   display:   { family: "Inter, system-ui, sans-serif", weight: 700 },
   bodyText:  { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.5 },
   numeric:   { family: "Inter, system-ui, sans-serif", weight: 500, tabular: false },
   scaleMode: "balanced" as const,
   ```
3. At the top level (alongside `color`, `spacing`, `radius`, etc.) add `density`, `elevation`, `motion`.

- [ ] **Step 3: Update TokenGroups type if needed**

The existing `TokenGroups` type uses `Record<string, Record<string, any>>` which already accepts string-typed values like `density: "comfortable"`. It should NOT need changes — but if TS complains about the new top-level scalar fields, widen the type to permit them.

- [ ] **Step 4: Run tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -20 || true

cd backend
python3 -m pytest tests/integration/test_schema_migration.py -v 2>&1 | tail -5
```

Expected: TS clean, migration 17/17 pass.

- [ ] **Step 5: Commit**

```bash
git add packages/library/src/theme/default-tokens.ts
git commit -m "feat(tokens): default values for density/elevation/radius.scale/typography.display+body+numeric/motion"
```

---

## Task 3: compileTokens emits new CSS variables

**Files:**
- Modify: `packages/renderer/src/runtime/tokens.ts`
- Create: `packages/library/src/theme/__tests__/compileTokens.test.ts`

- [ ] **Step 1: Read current compileTokens**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/packages/renderer/src/runtime/tokens.ts
```

- [ ] **Step 2: Extend compileTokens**

The existing function emits `--<group>-<key>: value` for nested keys (e.g. `--color-primary-500`, `--radius-md`). Extend it to also emit:
- `--density: comfortable | compact | spacious`
- `--elevation: layered | flat | bordered | floating`
- `--motion: subtle | none | expressive`
- `--radius-scale: soft | sharp | round`
- `--typography-display-family`, `--typography-display-weight`
- `--typography-bodyText-family`, `--typography-bodyText-weight`, `--typography-bodyText-lineHeight`
- `--typography-numeric-family`, `--typography-numeric-weight`, `--typography-numeric-tabular`
- `--typography-scaleMode: balanced | tight | dramatic`

The compiler probably has a generic walker. If so, the new groups should auto-emit. If it has special-cased some groups, add the new ones explicitly. Read the function and adapt.

- [ ] **Step 3: Write tests**

```ts
// packages/library/src/theme/__tests__/compileTokens.test.ts
import { describe, it, expect } from "vitest";
// or whatever testing framework the library package uses — check package.json

import { compileTokens } from "@tentoroforge/renderer";
import { defaultTokens } from "../default-tokens";

describe("compileTokens", () => {
  it("emits density as a flat var", () => {
    const css = compileTokens(defaultTokens as any);
    expect(css["--density"]).toBe("comfortable");
  });
  it("emits elevation as a flat var", () => {
    const css = compileTokens(defaultTokens as any);
    expect(css["--elevation"]).toBe("layered");
  });
  it("emits motion as a flat var", () => {
    const css = compileTokens(defaultTokens as any);
    expect(css["--motion"]).toBe("subtle");
  });
  it("emits radius.scale var", () => {
    const css = compileTokens(defaultTokens as any);
    expect(css["--radius-scale"]).toBe("soft");
  });
  it("emits typography.display.family + weight", () => {
    const css = compileTokens(defaultTokens as any);
    expect(css["--typography-display-family"]).toContain("Inter");
    expect(css["--typography-display-weight"]).toBe("700");
  });
  it("emits typography.numeric.tabular", () => {
    const css = compileTokens(defaultTokens as any);
    expect(css["--typography-numeric-tabular"]).toBe("false");
  });
  it("preserves existing color tokens", () => {
    const css = compileTokens(defaultTokens as any);
    expect(css["--color-primary-500"]).toBe("#3b82f6");
  });
});
```

NOTE: if the library package doesn't have a vitest setup, skip the test file and rely on visual regression to catch issues. Do NOT introduce a new testing framework.

- [ ] **Step 4: Run tests + visual regression**

```bash
# If vitest is present:
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library
npm test 2>&1 | tail -10

# Always: run visual regression to confirm nothing drifted
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-tokens.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 18/18 visual regression pass — emitting more CSS vars doesn't change rendered output as long as no component is reading them yet.

- [ ] **Step 5: Commit**

```bash
git add packages/renderer/src/runtime/tokens.ts packages/library/src/theme/__tests__/
git commit -m "feat(tokens): compileTokens emits CSS vars for new groups"
```

---

## Task 4: Tokens context provider

**Files:**
- Create: `packages/library/src/theme/tokens-context.tsx`
- Modify: `packages/library/src/index.ts` — re-export

- [ ] **Step 1: Implement provider**

```tsx
// packages/library/src/theme/tokens-context.tsx
"use client";

/**
 * React context for active tokens. Components read the active values via
 * useTokens() rather than re-parsing CSS variables, so derived values
 * (e.g. density-aware gap pixels) can be computed once per render.
 *
 * The provider is optional — components fall back to defaultTokens when
 * unwrapped. This keeps the existing schema-driven runtime working without
 * the editor or scaffold needing to install the provider.
 */

import * as React from "react";
import { defaultTokens } from "./default-tokens";

type TokenSnapshot = typeof defaultTokens;

const TokensContext = React.createContext<TokenSnapshot>(defaultTokens);

export function TokensProvider({
  tokens,
  children,
}: {
  tokens?: Partial<TokenSnapshot>;
  children: React.ReactNode;
}) {
  const merged = React.useMemo(() => {
    if (!tokens) return defaultTokens;
    return { ...defaultTokens, ...tokens } as TokenSnapshot;
  }, [tokens]);
  return <TokensContext.Provider value={merged}>{children}</TokensContext.Provider>;
}

export function useTokens(): TokenSnapshot {
  return React.useContext(TokensContext);
}

/** Convenience hooks for common reads. */
export function useDensity() {
  return useTokens().density as "compact" | "comfortable" | "spacious";
}
export function useElevation() {
  return useTokens().elevation as "flat" | "bordered" | "layered" | "floating";
}
export function useMotionLevel() {
  return useTokens().motion as "none" | "subtle" | "expressive";
}
export function useRadiusScale() {
  return useTokens().radius.scale as "sharp" | "soft" | "round";
}
```

- [ ] **Step 2: Re-export**

Edit `packages/library/src/index.ts` to add:
```ts
export * from "./theme/tokens-context";
```

- [ ] **Step 3: Verify**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true
```

- [ ] **Step 4: Commit**

```bash
git add packages/library/src/theme/tokens-context.tsx packages/library/src/index.ts
git commit -m "feat(tokens): TokensProvider + useTokens/useDensity/useElevation hooks"
```

---

## Task 5: Component refactor — Layout primitives (Stack, Section, Split, Sidebar, Cluster, Card, Hero)

These are the highest-leverage components to read tokens. Each gets density-aware default gaps + elevation-aware shadow/border treatment.

**Files:**
- Modify: `packages/library/src/components/Stack/Stack.tsx`
- Modify: `packages/library/src/components/Section/Section.tsx`
- Modify: `packages/library/src/components/Split/Split.tsx`
- Modify: `packages/library/src/components/Sidebar/Sidebar.tsx`
- Modify: `packages/library/src/components/Cluster/Cluster.tsx`
- Modify: `packages/library/src/components/Card/Card.tsx`
- Modify: `packages/library/src/components/Hero/Hero.tsx`

- [ ] **Step 1: Stack — density-aware default gap**

Read `Stack.tsx`. Find where its gap is applied. Today the schema's `gap` prop drives a gap class. Add a fallback: when the schema doesn't specify a gap, read `useDensity()` and pick a default:
- `compact` → `gap-2`
- `comfortable` → `gap-4` (today's default)
- `spacious` → `gap-6`

Pattern:
```tsx
import { useDensity } from "../../theme/tokens-context";

const DENSITY_GAP: Record<"compact"|"comfortable"|"spacious", string> = {
  compact: "gap-2",
  comfortable: "gap-4",
  spacious: "gap-6",
};

// Inside component:
const density = useDensity();
const fallbackGap = DENSITY_GAP[density];
const gapClass = props.gap ? gapClassFromProp(props.gap) : fallbackGap;
```

- [ ] **Step 2: Section — density-aware padding + elevation-aware border/shadow**

Layered on top of Wave 1's Section.role work. When role is undefined, read density + elevation:
- density.compact → `py-4`
- density.comfortable → `py-8` (today's default)
- density.spacious → `py-12`
- elevation.bordered → `border border-border`
- elevation.layered → `shadow-sm` (today's default)
- elevation.flat → no border, no shadow
- elevation.floating → `shadow-lg`

When role IS set, role still wins (preserves Wave 1 behavior).

- [ ] **Step 3: Split, Sidebar, Cluster — density-aware gaps**

Same pattern as Stack. Each picks its default gap from `useDensity()` when its own gap prop is absent.

- [ ] **Step 4: Card — density-aware padding (defaults to `regular` from Wave 1) + elevation-aware shadow**

Layered on top of Wave 1's Card.density work. When `density` prop is undefined, fall back to `useDensity()` global:
- global compact + no prop → `tight` equivalent (`p-3`)
- global comfortable + no prop → `regular` (`p-6`)
- global spacious + no prop → `loose` (`p-10`)

Elevation-aware: same mapping as Section. Card.elevation prop overrides if set.

- [ ] **Step 5: Hero — typography.scaleMode-aware sizing**

When `role` is undefined (Wave 1 default = banner), fall back to `useTokens().typography.scaleMode`:
- `tight` → headline text-xl, subhead text-sm
- `balanced` → headline text-2xl, subhead text-base (today's default)
- `dramatic` → headline text-4xl, subhead text-lg

When role IS set (Wave 1), role still wins (existing behavior).

- [ ] **Step 6: Run regression after each file**

After modifying each component, boot the frontend and run targeted regression:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-batch1.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test --grep "<ComponentName>"
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Each component's existing baseline must still pass — defaults preserve today's appearance.

- [ ] **Step 7: Single commit for the batch**

```bash
git add packages/library/src/components/{Stack,Section,Split,Sidebar,Cluster,Card,Hero}/
git commit -m "feat(library): layout primitives consume density/elevation/scaleMode tokens"
```

---

## Task 6: Component refactor — Data display (MetricTile, Heading, Badge, Avatar, KeyValueList, Table)

**Files:**
- Modify: `packages/library/src/components/MetricTile/MetricTile.tsx`
- Modify: `packages/library/src/components/Heading/Heading.tsx`
- Modify: `packages/library/src/components/Badge/Badge.tsx`
- Modify: `packages/library/src/components/Avatar/Avatar.tsx`
- Modify: `packages/library/src/components/KeyValueList/KeyValueList.tsx`
- Modify: `packages/library/src/components/Table/Table.tsx`

- [ ] **Step 1: MetricTile — typography.numeric + elevation**

Layered on Wave 1 importance work. The numeric value rendering should use `typography.numeric.family` + `typography.numeric.tabular`:

```tsx
import { useTokens } from "../../theme/tokens-context";

// Inside component:
const tokens = useTokens();
const valueStyle = {
  fontFamily: tokens.typography.numeric.family,
  fontWeight: tokens.typography.numeric.weight,
  fontVariantNumeric: tokens.typography.numeric.tabular ? "tabular-nums" : undefined,
};

// Apply to the value <p>:
<p className={cx.value} style={valueStyle}>{formatValue(...)}</p>
```

Elevation: pass-through to the tile's outer container. flat = no border + no shadow; layered = today's `shadow-sm`; bordered = border only; floating = `shadow-lg`.

- [ ] **Step 2: Heading — typography.display + scaleMode**

Layered on Wave 1 weight work. Use `typography.display.family` for level 1-2, `typography.bodyText.family` for level 3+. ScaleMode picks the size jump:
- tight: h1=2rem, h2=1.5rem, h3=1.25rem (today's)
- balanced: h1=2.5rem, h2=1.75rem, h3=1.375rem
- dramatic: h1=3.5rem, h2=2.25rem, h3=1.5rem

Default = balanced. Existing schemas don't set scaleMode → preserve today's tight-ish appearance via balanced default.

NOTE: the implementer's prior task report said Heading uses inline `style.fontWeight` via `tokenToCssVar` — keep that pattern; just add fontFamily + size resolution alongside.

- [ ] **Step 3: Badge — radius.scale + density**

Apply radius.scale to badge corner radius:
- sharp → `rounded-sm`
- soft → `rounded-md` (today's default)
- round → `rounded-full`

Density affects padding:
- compact → `px-1.5 py-0.5 text-[10px]`
- comfortable → `px-2 py-0.5 text-[11px]` (today's)
- spacious → `px-2.5 py-1 text-xs`

- [ ] **Step 4: Avatar — radius.scale**

Apply radius.scale to avatar corners. round = circle (today's default for most avatars). sharp = square. soft = rounded-md.

- [ ] **Step 5: KeyValueList — density-aware row spacing**

Each kv row's vertical gap follows density:
- compact → `gap-x-3 gap-y-1`
- comfortable → `gap-x-4 gap-y-2` (today's)
- spacious → `gap-x-6 gap-y-3`

- [ ] **Step 6: Table — density-aware row height**

Each `<tr>` cell padding follows density:
- compact → `px-3 py-1.5 text-xs`
- comfortable → `px-4 py-2 text-sm` (today's)
- spacious → `px-6 py-3 text-base`

- [ ] **Step 7: Run regression**

After all 6 changes, boot frontend, run full regression suite:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-batch2.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 18/18 pass. If any fail, the implementer's defaults didn't match today's appearance — adjust until they do.

- [ ] **Step 8: Commit**

```bash
git add packages/library/src/components/{MetricTile,Heading,Badge,Avatar,KeyValueList,Table}/
git commit -m "feat(library): data display components consume typography/density/radius tokens"
```

---

## Task 7: Component refactor — Forms (Input, Textarea, Select, DatePicker, Checkbox, Form)

**Files:**
- Modify: `packages/library/src/components/{Input,Textarea,Select,DatePicker,Checkbox,Form}/<X>.tsx`

- [ ] **Step 1: Input/Textarea/Select/DatePicker — radius.scale + density**

Each input gets:
- Radius: sharp → `rounded-sm`, soft → `rounded-md` (today's), round → `rounded-lg`
- Density (input height):
  - compact → `h-8 px-2 text-xs`
  - comfortable → `h-10 px-3 text-sm` (today's)
  - spacious → `h-12 px-4 text-base`

- [ ] **Step 2: Checkbox — radius.scale**

Sharp → `rounded-none`, soft → `rounded` (today's), round → `rounded-md`.

- [ ] **Step 3: Form — density-aware field gap**

Vertical gap between fields:
- compact → `space-y-3`
- comfortable → `space-y-4` (today's default)
- spacious → `space-y-6`

- [ ] **Step 4: Run regression + commit**

```bash
git add packages/library/src/components/{Input,Textarea,Select,DatePicker,Checkbox,Form}/
git commit -m "feat(library): form components consume radius.scale + density tokens"
```

---

## Task 8: Component refactor — Feedback + Nav (Skeleton, Alert, EmptyState, LoadingState, Tabs, Accordion, Breadcrumb)

**Files:**
- Modify: `packages/library/src/components/{Skeleton,Alert,EmptyState,LoadingState,Tabs,Accordion,Breadcrumb}/<X>.tsx`

- [ ] **Step 1: Skeleton/Alert/EmptyState/LoadingState — radius.scale + elevation**

Each gets corner radius from `radius.scale` and (where applicable) elevation:
- Alert with elevation.bordered → border-only (no shadow)
- Alert with elevation.layered → border + shadow-sm (today's)
- EmptyState card → same elevation rules

- [ ] **Step 2: Tabs/Accordion — density.gap**

Tab strip horizontal gap follows density. Accordion item vertical gap follows density.

- [ ] **Step 3: Breadcrumb — density-aware separator spacing**

`gap-x-{1|2|3}` per density.

- [ ] **Step 4: Run regression + commit**

```bash
git add packages/library/src/components/{Skeleton,Alert,EmptyState,LoadingState,Tabs,Accordion,Breadcrumb}/
git commit -m "feat(library): feedback + nav components consume radius/density/elevation"
```

---

## Task 9: schema_prompt surfaces new tokens

**Files:**
- Modify: `backend/services/schema_prompt.py`

- [ ] **Step 1: Update render_token_paths**

The existing `render_token_paths()` walks `defaultTokens` and emits paths like `tokens.color.primary.500`. The new groups (density, elevation, motion) are scalars, not nested — extend the walker to emit them too:
- `tokens.density` (value: "comfortable")
- `tokens.elevation` (value: "layered")
- `tokens.motion` (value: "subtle")
- `tokens.radius.scale` (value: "soft")
- `tokens.typography.display.family`, etc.

These end up in the prompt as available token paths, so the LLM knows it can bind to them.

- [ ] **Step 2: Add a TOKENS_NEW_GROUPS guidance block**

Append to the prompt (after HIERARCHY_GUIDANCE from Wave 1):

```python
TOKENS_NEW_GROUPS_GUIDANCE = """
## NEW TOKEN GROUPS (Wave 2)

Beyond color, the design system now has these knobs:

  density: compact | comfortable | spacious
    Drives default gaps + paddings. Use compact for data-dense pages
    (HR / fintech tables), spacious for marketing / content pages.

  elevation: flat | bordered | layered | floating
    flat = no shadow no border (Notion-like)
    bordered = border only (Linear-like)
    layered = shadow-sm + border (default)
    floating = shadow-lg (Stripe-like hero treatment)

  radius.scale: sharp | soft | round
    sharp = 4px (Linear)
    soft = 8px (default — shadcn-like)
    round = 12px (Notion-like)

  typography.display: family for headlines (hero text, page titles)
  typography.bodyText: family for paragraphs and labels
  typography.numeric: family for metric values (often a tabular face)
  typography.scaleMode: tight | balanced | dramatic — H1→H6 size jump

  motion: none | subtle | expressive

Most schemas don't need to set these — they inherit from the project's
register (Wave 3). When you DO set them, set them on the root node so they
cascade.
"""
```

- [ ] **Step 3: Run + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_schema_prompt.py -v 2>&1 | tail -10

git add backend/services/schema_prompt.py
git commit -m "feat(schema-prompt): surface density/elevation/typography token groups"
```

---

## Task 10: Editor Style tab — selectors for new groups

**Files:**
- Modify: `frontend/src/components/schema-editor/PropertiesPanel/Style.tsx`

- [ ] **Step 1: Find the Style tab**

```bash
find /Users/m/Work/code/poc/design2ui-forge-v3/frontend/src/components/schema-editor -name "Style*" -o -name "*Style*" | head -5
```

- [ ] **Step 2: Add three new selectors**

For the active node, add three select inputs:
- Density: compact / comfortable / spacious (writes `props.density` if the node accepts it; else writes a project-level token override)
- Elevation: flat / bordered / layered / floating (same)
- Radius scale: sharp / soft / round

Match the existing select pattern in the Style tab. Don't introduce a new UI library — reuse what's there.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/schema-editor/PropertiesPanel/Style.tsx
git commit -m "feat(editor): Style tab selectors for density/elevation/radius.scale"
```

NOTE: this task is NICE TO HAVE. If the Style tab has an unusual structure that makes the addition non-trivial, mark it DONE_WITH_CONCERNS and move on — the tokens are still configurable via tokens.custom.json directly. The editor convenience can land in a follow-up.

---

## Task 11: Migration safety net — final verification

- [ ] **Step 1: Run all tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/integration/test_schema_migration.py tests/services/test_schema_prompt.py tests/agents/test_patch_agent.py -v 2>&1 | tail -15
```

Expected: all PASS, including 17/17 migration fixtures.

- [ ] **Step 2: Run full visual regression**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-final.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 18/18 pass.

- [ ] **Step 3: render-scaffold parity**

The render-scaffold (port 6503) and editor (port 6501) both use the library. After Wave 2, the same schema must render identically in both. Boot scaffold:

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
cd apps/render-scaffold && npm run dev > /tmp/scaffold-final.log 2>&1 &
sleep 10
PROJ=$(ls /Users/m/Work/code/poc/design2ui-forge-v3/output | head -1)
[ -n "$PROJ" ] && curl -s -o /dev/null -w "scaffold: %{http_code}\n" "http://localhost:6503/p/$PROJ/"
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
```

Expected: 200 (or 404 if no schemas in that project — fine, just confirming the scaffold boots cleanly with the new library).

- [ ] **Step 4: Commit a final marker (optional)**

If any baseline updates or test fixture refreshes were needed during this verification, commit them. Otherwise nothing to commit at this step.

---

## Self-review

### Spec coverage

| Spec section | Tasks |
|---|---|
| Token schema + types | 1, 2 |
| Token compiler | 3 |
| Tokens context provider | 4 |
| Component refactor batches | 5 (layout), 6 (data), 7 (forms), 8 (feedback+nav) |
| Schema agent integration | 9 |
| Editor integration | 10 |
| Migration safety | 11 |

✓ All Phase 2 spec items covered.

### Type consistency

- New `Density`, `Elevation`, `Motion`, `RadiusScale`, `ScaleMode` types defined in `packages/library/src/theme/token-types.ts` (Task 1)
- Used consistently across all components (Tasks 5-8)
- `useTokens()` hooks return strongly-typed values
- defaultTokens preserves today's appearance via carefully chosen defaults

✓ Consistent.

### Backward compatibility

Every component change includes a "default = today's appearance" path. Existing schemas don't reference the new tokens — they inherit the defaults — and render identically to before. Visual regression suite at 18/18 throughout the wave is the proof.

---

## Out of scope (deferred to Wave 3+)

- **Stylistic registers** (Workday/Linear/Stripe/Notion/Figma) that override these defaults — Wave 3
- **Per-component register variants** — Wave 3
- **Reference bank re-seeding for new visual register** — Wave 3
- **Motion micro-interactions** — Wave 5 (motion token exists; Stagger/FadeIn already wired)
- **Editor preview switch** for density/elevation toggling without persistence — Wave 5
- **Per-domain rubric weight tuning** — Wave 5
