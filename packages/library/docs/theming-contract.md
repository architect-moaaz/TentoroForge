# Library Theming Contract

## Why the library themes per-project

Design2UI generates apps for multiple clients, each with its own brand palette.
The library ships one set of components that must adopt any project's brand
automatically — no per-client component forks. It achieves this through a
two-layer system:

1. **CSS custom properties injected by `EngineProvider`** — at runtime the
   engine walks `tokens.custom.json` and writes both raw token vars
   (`--color-primary-500`, `--color-success-100`, …) and shadcn-style semantic
   vars (`--primary`, `--muted`, `--destructive`, …) onto the root wrapper div.

2. **Tailwind utilities that read those vars** — `bg-primary`, `text-foreground`,
   `bg-muted`, etc. resolve against whatever the wrapper declares, so every
   component inside `<EngineProvider>` gets the project's brand for free.

## Semantic CSS vars injected by `tokensToSemanticVars`

These 29 vars are written onto the `data-tentoro-engine` wrapper at render time.
Source token paths are relative to the project's `color` subtree.

| CSS variable | Source token path | Tailwind class equivalent |
|---|---|---|
| `--background` | `color.surface.0` | `bg-background` |
| `--foreground` | `color.primary.900` | `text-foreground` |
| `--card` | `color.surface.1` | `bg-card` |
| `--card-foreground` | `color.primary.900` | `text-card-foreground` |
| `--popover` | `color.surface.1` | `bg-popover` |
| `--popover-foreground` | `color.primary.900` | `text-popover-foreground` |
| `--primary` | `color.primary.600` | `bg-primary` / `text-primary` |
| `--primary-foreground` | `color.surface.0` | `text-primary-foreground` |
| `--secondary` | `color.secondary.100` | `bg-secondary` |
| `--secondary-foreground` | `color.secondary.900` | `text-secondary-foreground` |
| `--muted` | `color.primary.50` | `bg-muted` |
| `--muted-foreground` | `color.primary.700` | `text-muted-foreground` |
| `--accent` | `color.accent.100` (or `.500`) | `bg-accent` |
| `--accent-foreground` | `color.accent.900` | `text-accent-foreground` |
| `--destructive` | `color.error.500` | `bg-destructive` / `text-destructive` |
| `--border` | `color.primary.100` | `border-border` |
| `--input` | `color.primary.100` | `border-input` |
| `--ring` | `color.primary.500` | `ring-ring` |
| `--sidebar` | `color.surface.1` | `bg-sidebar` |
| `--sidebar-foreground` | `color.primary.900` | `text-sidebar-foreground` |
| `--sidebar-primary` | `color.primary.600` | `bg-sidebar-primary` |
| `--sidebar-primary-foreground` | `color.surface.0` | `text-sidebar-primary-foreground` |
| `--sidebar-accent` | `color.primary.50` | `bg-sidebar-accent` |
| `--sidebar-accent-foreground` | `color.primary.900` | `text-sidebar-accent-foreground` |
| `--sidebar-border` | `color.primary.100` | `border-sidebar-border` |
| `--sidebar-ring` | `color.primary.500` | `ring-sidebar-ring` |
| `--success` | `color.success.500` | `bg-[var(--success)]` |
| `--warning` | `color.warning.500` | `bg-[var(--warning)]` |
| `--info` | `color.secondary.500` | `bg-[var(--info)]` |

> **Note:** vars are only emitted when the source token is present in the
> project's token tree. Missing tokens leave the shadcn `:root` defaults intact.

## The contract

### PREFER — shadcn semantic classes

Use shadcn semantic utilities for all common surface/text/border needs. They
theme per-project with zero extra work:

```tsx
// Good — themes automatically
<div className="bg-card text-card-foreground border-border rounded-lg" />
<button className="bg-primary text-primary-foreground hover:bg-primary/90" />
<p className="text-muted-foreground" />
```

### EXPLICIT BRAND COLOR STEP — CSS var with Tailwind fallback

When you need a specific tonal step of the brand palette (e.g. a gradient or
a tinted hover ring that shadcn's single `--primary` can't express), reach
into the raw token vars:

```tsx
// Acceptable — explicit step, safe fallback
<div className="bg-[var(--color-primary-50,theme(colors.slate.50))]" />
<div className="from-[var(--color-primary-600,theme(colors.blue.600))] to-[var(--color-primary-800,theme(colors.blue.800))]" />
```

The `theme(colors.X.N)` fallback ensures the component still renders correctly
in a context where `EngineProvider` is absent (unit tests, Storybook, etc.).

### STATUS COLORS — semantic, not brand

Success / warning / error / info carry meaning that must NOT shift when the
project swaps its brand from blue to teal. Use status-specific vars:

```tsx
// Status colors — semantic, always green/amber/red regardless of brand
<span className="bg-[var(--color-success-100,theme(colors.emerald.100))] text-[var(--color-success-800,theme(colors.emerald.800))]" />
<span className="bg-[var(--color-error-100,theme(colors.red.100))] text-[var(--color-error-800,theme(colors.red.800))]" />
<span className="bg-[var(--color-warning-100,theme(colors.amber.100))] text-[var(--color-warning-800,theme(colors.amber.800))]" />
```

For the top-level single-tone status surface (`--destructive` is the only
built-in shadcn one), prefer `bg-destructive text-destructive-foreground`.
For success/warning/info there is no shadcn equivalent — use the CSS var
pattern above.

### HARD BAN — raw Tailwind palette classes

**Never** use a raw Tailwind palette utility inside a library component:

```tsx
// BANNED — will fail the lint test
<div className="bg-slate-50 text-slate-900" />
<span className="text-red-700 bg-red-100" />
<div className="border-emerald-200" />
```

**Why:** Raw palette classes are unconditionally compiled into Tailwind's output
and hard-code specific colors. They cannot theme per-project and they silently
conflict with projects that use a non-default brand (e.g. a purple-primary
project still sees green `bg-emerald-*` badges).

**Lint enforcement:** `packages/library/tests/theming-contract.test.ts` runs
a regex scan over all component TSX files and fails if any of the following
prefixes appear with a palette color name + numeric step:

```
bg-|text-|border-|from-|to-|ring-|outline-|divide-
```

followed by any of the 22 standard Tailwind color names and a 2–3-digit step
(e.g. `bg-rose-50`, `text-emerald-700`).

## Migration cheat sheet

| Before (banned) | After (preferred) |
|---|---|
| `bg-slate-50` | `bg-muted` or `bg-[var(--color-primary-50,theme(colors.slate.50))]` |
| `bg-slate-100` | `bg-muted` or `bg-[var(--color-primary-100,theme(colors.slate.100))]` |
| `text-slate-900` | `text-foreground` |
| `text-slate-500` / `text-gray-500` | `text-muted-foreground` |
| `border-slate-200` | `border-border` |
| `bg-blue-100 text-blue-800` | `bg-[var(--color-primary-100,theme(colors.blue.100))] text-[var(--color-primary-800,theme(colors.blue.800))]` |
| `bg-emerald-100 text-emerald-800` | `bg-[var(--color-success-100,theme(colors.emerald.100))] text-[var(--color-success-800,theme(colors.emerald.800))]` |
| `bg-red-100 text-red-800` | `bg-[var(--color-error-100,theme(colors.red.100))] text-[var(--color-error-800,theme(colors.red.800))]` |
| `bg-amber-100 text-amber-800` | `bg-[var(--color-warning-100,theme(colors.amber.100))] text-[var(--color-warning-800,theme(colors.amber.800))]` |
| `bg-red-500` / `bg-destructive` (error surface) | `bg-destructive text-destructive-foreground` |
| `bg-white` | `bg-background` or `bg-card` |
| `text-black` / `text-gray-900` | `text-foreground` |

## Known palette holdouts — WS-5 follow-up

The following 10 component files still contain raw palette classes. They are
grandfathered in the lint test (`ALLOWED_HOLDOUTS`) until a dedicated migration
pass (tracked as WS-5 follow-up). The palette uses are mostly status/semantic
colors that require careful per-context review before migrating:

- `ApprovalStepper/ApprovalStepper.tsx`
- `PersonCard/PersonCard.tsx`
- `ActivityFeed/ActivityFeed.tsx`
- `Timeline/Timeline.tsx`
- `MetricTile/MetricTile.tsx`
- `MetricTile/MetricTile.linear.tsx`
- `MetricTile/MetricTile.stripe.tsx`
- `MetricTile/MetricTile.workday.tsx`
- `MetricTile/MetricTile.figma.tsx`
- `MetricTile/MetricTile.notion.tsx`
