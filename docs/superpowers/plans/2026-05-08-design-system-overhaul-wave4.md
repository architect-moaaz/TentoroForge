# Design System Overhaul — Wave 4: Remaining 4 Registers + Intelligence

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship Linear / Stripe / Notion / Figma stylistic registers + the planner's domain × register selection intelligence + editor manual-override controls. After Wave 4, every supported domain gets a domain-appropriate register; the framework that Wave 3 established with Workday is now realised across all 5 registers.

**Architecture:** Each register is a token bundle (`packages/library/src/theme/registers/<name>.ts`) following the Wave 3 Workday template. Components reuse the same Wave 3 variant structure where the visual treatment differs from the default — components without a register-specific variant fall back to defaults (with token-driven appearance per the bundle). Planner gains a richer classification table; editor gets a manual register override.

**Tech Stack:** Same as Waves 1-3 — TypeScript / React 19 / Tailwind / Zod. No new deps. Each register reuses the existing `RegisterName` / `RegisterBundle` / `selectVariant` machinery from Wave 3.

**Spec:** `docs/superpowers/specs/2026-05-08-design-system-overhaul-design.md` § Phases 4 + 5.

---

## File structure

### New files (4 register bundles + 4×3 variant files)

**Register bundles:**
- `packages/library/src/theme/registers/linear.ts`
- `packages/library/src/theme/registers/stripe.ts`
- `packages/library/src/theme/registers/notion.ts`
- `packages/library/src/theme/registers/figma.ts`

**Component variants (3 components × 4 registers = 12 new files):**
- `packages/library/src/components/MetricTile/MetricTile.{linear,stripe,notion,figma}.tsx`
- `packages/library/src/components/Card/Card.{linear,stripe,notion,figma}.tsx`
- `packages/library/src/components/Hero/Hero.{linear,stripe,notion,figma}.tsx`

**Intelligence:**
- `backend/services/register_selector.py` — domain × register mapping table + selector

### Modified files

- `packages/library/src/theme/registers/index.ts` — register all 4 new bundles in REGISTRY
- `packages/library/src/components/variants/index.ts` — register all 12 new variants in VARIANTS map
- `backend/agents/planner.py` — call `register_selector.classify_register` instead of inline heuristics
- `frontend/src/components/schema-editor/SchemaEditorPanel.tsx` — manual register override dropdown
- `backend/routers/_debug_schema.py` — endpoint to update design-spec.json (for the override)
- `backend/services/reference_bank.py` — `available_registers()` helper

---

## Task 1: Linear-tier register

**Files:**
- Create: `packages/library/src/theme/registers/linear.ts`
- Create: `packages/library/src/components/MetricTile/MetricTile.linear.tsx`
- Create: `packages/library/src/components/Card/Card.linear.tsx`
- Create: `packages/library/src/components/Hero/Hero.linear.tsx`

### Linear-tier defining traits

Monochrome neutral, sharp edges, dense, single accent. SaaS / developer-tools feel.

### Step 1: Token bundle

```ts
// packages/library/src/theme/registers/linear.ts
import type { RegisterBundle } from "./types";

export const linearRegister: RegisterBundle = {
  name: "linear",
  description: "Monochrome neutral, sharp edges, single accent — SaaS / dev tools.",
  tokens: {
    color: {
      primary: {
        "50":  "#fafafa", "100": "#f4f4f5", "200": "#e4e4e7", "300": "#d4d4d8",
        "400": "#a1a1aa", "500": "#5e6ad2", "600": "#4f5cc4", "700": "#3f4ab0",
        "800": "#323b8e", "900": "#252b6a", "950": "#171b46",
      },
      secondary: {
        "50":  "#fafafa", "100": "#f4f4f5", "200": "#e4e4e7", "300": "#d4d4d8",
        "400": "#a1a1aa", "500": "#71717a", "600": "#52525b", "700": "#3f3f46",
        "800": "#27272a", "900": "#18181b", "950": "#09090b",
      },
      surface: { "0": "#ffffff", "1": "#fafafa", "2": "#f4f4f5" },
      border:  { default: "#e4e4e7" },
      muted:   { default: "#a1a1aa" },
      text:    { primary: "#18181b", secondary: "#52525b", tertiary: "#a1a1aa" },
      sidebar: { bg: "#ffffff", text: "#52525b", active: "#5e6ad2" },
    },
    typography: {
      font:     { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
      display:  { family: "Inter, system-ui, sans-serif", weight: 600 },
      bodyText: { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.45 },
      numeric:  { family: "ui-monospace, SFMono-Regular, monospace", weight: 500, tabular: true },
      scaleMode: "tight",
    },
    radius: { scale: "sharp" },
    density: "compact",
    elevation: "flat",
    motionLevel: "subtle",
  },
};
```

### Step 2: Linear variants (3 components)

Pattern: each variant follows the Wave 3 Workday template but with Linear's visual language. Read the Wave 3 file (`MetricTile.workday.tsx`) for reference.

**MetricTile.linear.tsx** — flat tile (no border, just bg-muted/30 panel), small primary value with mono numerics, NO sparkline by default (Linear style is data-first not visual-first), tiny delta in monospace:

```tsx
// packages/library/src/components/MetricTile/MetricTile.linear.tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface LinearMetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

const TILE = "flex flex-col gap-1 bg-muted/40 px-4 py-3";
const LABEL = "text-[10px] font-medium uppercase tracking-wider text-muted-foreground";
const VALUE = "text-xl font-medium leading-none tabular-nums text-foreground font-mono";
const DELTA = "inline-flex items-center gap-1 text-[10px] font-mono tabular-nums";

const DELTA_GLYPH = { up: "+", down: "−", flat: "·" } as const;
const DELTA_TONE: Record<"up"|"down"|"flat", string> = {
  up:   "text-emerald-600",
  down: "text-rose-600",
  flat: "text-muted-foreground",
};

function fmtValue(v: number | string, format: MetricTilePropsType["format"]): string {
  if (typeof v === "string") return v;
  if (format === "currency") return `$${new Intl.NumberFormat("en-US").format(v)}`;
  if (format === "percent")  return `${(v * 100).toFixed(0)}%`;
  if (format === "duration") return `${v}s`;
  return new Intl.NumberFormat("en-US").format(v);
}

export function MetricTileLinear({ label, value, format, delta, style }: LinearMetricTileProps) {
  return (
    <div className={TILE} style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <p className={LABEL}>{label}</p>
      <p className={VALUE}>{fmtValue(value, format)}</p>
      {delta && (
        <span className={`${DELTA} ${DELTA_TONE[delta.direction]}`}>
          <span>{DELTA_GLYPH[delta.direction]}{Math.abs(delta.value * 100).toFixed(0)}%</span>
        </span>
      )}
    </div>
  );
}
```

**Card.linear.tsx** — flat (no border, no shadow), subtle muted bg, single keyboard-shortcut hint slot (Linear convention):

```tsx
// packages/library/src/components/Card/Card.linear.tsx
import * as React from "react";
import { resolveStyle } from "../../style/resolveStyle";

interface LinearCardProps {
  title?: React.ReactNode;
  footer?: React.ReactNode;
  children?: React.ReactNode;
  style?: any;
}

export function CardLinear({ title, footer, children, style }: LinearCardProps) {
  return (
    <div className="bg-muted/30" style={resolveStyle(style)}>
      {title && <div className="px-4 py-2.5 text-xs font-medium text-foreground">{title}</div>}
      <div className="px-4 py-3 text-sm">{children}</div>
      {footer && <div className="px-4 py-2 border-t border-border/50 text-xs text-muted-foreground">{footer}</div>}
    </div>
  );
}
```

**Hero.linear.tsx** — minimal page header (no background, just typography), small caps eyebrow:

```tsx
// packages/library/src/components/Hero/Hero.linear.tsx
import * as React from "react";
import { resolveStyle } from "../../style/resolveStyle";

interface LinearHeroProps {
  eyebrow?: string;
  headline?: string;
  subhead?: string;
  ctas?: Array<{ label: string; action?: any }>;
  children?: React.ReactNode;
  style?: any;
}

export function HeroLinear({ eyebrow, headline, subhead, ctas, children, style }: LinearHeroProps) {
  return (
    <header className="px-6 py-5" style={resolveStyle(style)}>
      {eyebrow && <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-1">{eyebrow}</p>}
      {headline && <h1 className="text-xl font-semibold leading-tight tracking-tight text-foreground">{headline}</h1>}
      {subhead && <p className="mt-1 text-sm text-muted-foreground">{subhead}</p>}
      {ctas && ctas.length > 0 && (
        <div className="mt-3 flex items-center gap-2">
          {ctas.map((cta, i) => (
            <button key={i} type="button" className="h-7 px-3 text-xs font-medium rounded-sm bg-foreground text-background hover:bg-foreground/90">
              {cta.label}
            </button>
          ))}
        </div>
      )}
      {children}
    </header>
  );
}
```

### Step 3: Register the bundle + variants

In `packages/library/src/theme/registers/index.ts`:
```ts
import { linearRegister } from "./linear";
// In the REGISTRY map:
const REGISTRY: Partial<Record<RegisterName, RegisterBundle>> = {
  workday: workdayRegister,
  linear: linearRegister,  // ← add
};
```

In `packages/library/src/components/variants/index.ts`:
```ts
import { MetricTileLinear } from "../MetricTile/MetricTile.linear";
import { CardLinear } from "../Card/Card.linear";
import { HeroLinear } from "../Hero/Hero.linear";

const VARIANTS: Record<string, Partial<Record<RegisterName, React.ComponentType<any>>>> = {
  MetricTile: { workday: MetricTileWorkday, linear: MetricTileLinear },
  Card:       { workday: CardWorkday,       linear: CardLinear },
  Hero:       { workday: HeroWorkday,       linear: HeroLinear },
};
```

### Step 4: Verify build + visual regression

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -20 || true

# Library rebuild needed if dist is consumed by scaffold
cd packages/library && npm run build 2>&1 | tail -5

cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-w4-linear.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 18/18 PASS — playground doesn't mount Linear register so defaults still apply.

### Step 5: Commit

```bash
git add packages/library/src/theme/registers/linear.ts \
        packages/library/src/components/{MetricTile,Card,Hero}/*.linear.tsx \
        packages/library/src/theme/registers/index.ts \
        packages/library/src/components/variants/index.ts
git commit -m "feat(registers): Linear-tier register + MetricTile/Card/Hero variants"
```

---

## Task 2: Stripe-tier register

Same pattern as Task 1. Stripe-tier defining traits: gradient hero, layered shadow elevation, generous padding, two-tone palette, structured data-grid feel. Best for fintech / payments / financial reporting.

### Token bundle (`packages/library/src/theme/registers/stripe.ts`)

```ts
import type { RegisterBundle } from "./types";

export const stripeRegister: RegisterBundle = {
  name: "stripe",
  description: "Two-tone with gradient hero, layered shadows — fintech / payments.",
  tokens: {
    color: {
      primary: {
        "50":  "#f5f3ff", "100": "#ede9fe", "200": "#ddd6fe", "300": "#c4b5fd",
        "400": "#a78bfa", "500": "#635bff", "600": "#5046e5", "700": "#3f37c0",
        "800": "#322b96", "900": "#252072", "950": "#15124a",
      },
      secondary: {
        "50":  "#f8fafc", "100": "#f1f5f9", "200": "#e2e8f0", "300": "#cbd5e1",
        "400": "#94a3b8", "500": "#64748b", "600": "#475569", "700": "#334155",
        "800": "#1e293b", "900": "#0f172a", "950": "#020617",
      },
      surface: { "0": "#ffffff", "1": "#f8fafc", "2": "#f1f5f9" },
      border:  { default: "#e4e4e7" },
      muted:   { default: "#a1a1aa" },
      text:    { primary: "#0a0a23", secondary: "#425466", tertiary: "#8898aa" },
      sidebar: { bg: "#0a0a23", text: "#cbd5e1", active: "#635bff" },
    },
    typography: {
      font:     { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
      display:  { family: "Inter, system-ui, sans-serif", weight: 700 },
      bodyText: { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.55 },
      numeric:  { family: "ui-monospace, SFMono-Regular, monospace", weight: 500, tabular: true },
      scaleMode: "balanced",
    },
    radius: { scale: "soft" },
    density: "comfortable",
    elevation: "layered",
    motionLevel: "subtle",
  },
};
```

### Variants (Stripe-flavored)

Each variant follows the same structure as Linear/Workday. Stripe flavor:

- **MetricTile.stripe.tsx** — gradient-tinted card (`bg-gradient-to-br from-primary/5 to-primary/0`), confident numeric, prominent delta
- **Card.stripe.tsx** — soft border + shadow-sm + rounded-md, gradient header strip when title present
- **Hero.stripe.tsx** — gradient bg from primary/5 to background, big confident headline, prominent CTA buttons with subtle shadow

The implementer follows the Linear template pattern, swapping classes for Stripe's visual language. Don't over-engineer; ~30 lines per variant.

### Register + commit

```bash
git add packages/library/src/theme/registers/stripe.ts \
        packages/library/src/components/{MetricTile,Card,Hero}/*.stripe.tsx \
        packages/library/src/theme/registers/index.ts \
        packages/library/src/components/variants/index.ts
git commit -m "feat(registers): Stripe-tier register + MetricTile/Card/Hero variants"
```

---

## Task 3: Notion-tier register

Notion-tier traits: soft grays, generous spacing, no shadows, content-first, rounded corners (12px). Best for content / docs / knowledge bases.

### Token bundle (`packages/library/src/theme/registers/notion.ts`)

```ts
import type { RegisterBundle } from "./types";

export const notionRegister: RegisterBundle = {
  name: "notion",
  description: "Soft, airy, content-first — wikis / docs / knowledge bases.",
  tokens: {
    color: {
      primary: {
        "50":  "#fafaf9", "100": "#f5f5f4", "200": "#e7e5e4", "300": "#d6d3d1",
        "400": "#a8a29e", "500": "#78716c", "600": "#57534e", "700": "#44403c",
        "800": "#292524", "900": "#1c1917", "950": "#0c0a09",
      },
      secondary: {
        "50":  "#fafaf9", "100": "#f5f5f4", "200": "#e7e5e4", "300": "#d6d3d1",
        "400": "#a8a29e", "500": "#78716c", "600": "#57534e", "700": "#44403c",
        "800": "#292524", "900": "#1c1917", "950": "#0c0a09",
      },
      surface: { "0": "#ffffff", "1": "#fafaf9", "2": "#f5f5f4" },
      border:  { default: "#e7e5e4" },
      muted:   { default: "#a8a29e" },
      text:    { primary: "#1c1917", secondary: "#57534e", tertiary: "#a8a29e" },
      sidebar: { bg: "#fafaf9", text: "#57534e", active: "#1c1917" },
    },
    typography: {
      font:     { body: "ui-serif, Georgia, serif", heading: "ui-serif, Georgia, serif" },
      display:  { family: "ui-serif, Georgia, serif", weight: 600 },
      bodyText: { family: "ui-serif, Georgia, serif", weight: 400, lineHeight: 1.7 },
      numeric:  { family: "ui-sans-serif, system-ui", weight: 500, tabular: false },
      scaleMode: "dramatic",
    },
    radius: { scale: "round" },
    density: "spacious",
    elevation: "flat",
    motionLevel: "subtle",
  },
};
```

### Variants

- **MetricTile.notion.tsx** — no border, larger spacing, serif typography
- **Card.notion.tsx** — no border, generous padding, soft hover-state lift via subtle bg shift
- **Hero.notion.tsx** — generous space, serif headline, simple CTA links (not buttons)

### Commit

```bash
git commit -m "feat(registers): Notion-tier register + MetricTile/Card/Hero variants"
```

---

## Task 4: Figma-tier register

Figma-tier traits: vibrant palette, friendly numerics, density.comfortable, elevation.floating, radius.round. Best for design tools / creative apps.

### Token bundle (`packages/library/src/theme/registers/figma.ts`)

```ts
import type { RegisterBundle } from "./types";

export const figmaRegister: RegisterBundle = {
  name: "figma",
  description: "Vibrant, friendly, playful — design tools / creative apps.",
  tokens: {
    color: {
      primary: {
        "50":  "#fff1f2", "100": "#ffe4e6", "200": "#fecdd3", "300": "#fda4af",
        "400": "#fb7185", "500": "#f24e1e", "600": "#dc2626", "700": "#b91c1c",
        "800": "#991b1b", "900": "#7f1d1d", "950": "#450a0a",
      },
      secondary: {
        "50":  "#eff6ff", "100": "#dbeafe", "200": "#bfdbfe", "300": "#93c5fd",
        "400": "#60a5fa", "500": "#0d99ff", "600": "#1e40af", "700": "#1e3a8a",
        "800": "#172554", "900": "#0f172a", "950": "#020617",
      },
      accent: {
        "50":  "#f0fdf4", "100": "#dcfce7", "200": "#bbf7d0", "300": "#86efac",
        "400": "#4ade80", "500": "#a259ff", "600": "#16a34a", "700": "#15803d",
        "800": "#166534", "900": "#14532d", "950": "#052e16",
      },
      surface: { "0": "#ffffff", "1": "#f8fafc", "2": "#f1f5f9" },
      border:  { default: "#e4e4e7" },
      muted:   { default: "#a1a1aa" },
      text:    { primary: "#1c1917", secondary: "#52525b", tertiary: "#a1a1aa" },
      sidebar: { bg: "#1c1917", text: "#a1a1aa", active: "#f24e1e" },
    },
    typography: {
      font:     { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
      display:  { family: "Inter, system-ui, sans-serif", weight: 800 },
      bodyText: { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.5 },
      numeric:  { family: "Inter, system-ui, sans-serif", weight: 600, tabular: false },
      scaleMode: "balanced",
    },
    radius: { scale: "round" },
    density: "comfortable",
    elevation: "floating",
    motionLevel: "expressive",
  },
};
```

### Variants

- **MetricTile.figma.tsx** — colorful tile with gradient accent, friendly rounded-2xl, big colorful numeric
- **Card.figma.tsx** — rounded-2xl, shadow-lg, optional gradient border
- **Hero.figma.tsx** — colorful background, big bold headline, playful CTAs with bold rounded buttons

### Commit

```bash
git commit -m "feat(registers): Figma-tier register + MetricTile/Card/Hero variants"
```

---

## Task 5: Domain × register intelligence

**Files:**
- Create: `backend/services/register_selector.py`
- Modify: `backend/agents/planner.py` — call into the new selector

### Step 1: Create register_selector.py

```python
# backend/services/register_selector.py
"""Domain × register selection intelligence.

Picks the most appropriate stylistic register for a project based on the
brief and inferred domain. v1 — rule-based heuristics with explicit mapping
table. Future versions can use a small classifier LLM call when the
heuristics are ambiguous.
"""
from __future__ import annotations

from typing import Literal


RegisterName = Literal["default", "workday", "linear", "stripe", "notion", "figma"]


# Domain × register mapping table — primary affinity per domain.
DOMAIN_REGISTER_MAP: dict[str, RegisterName] = {
    "hr":          "workday",
    "healthcare":  "workday",
    "fintech":     "stripe",
    "finance":     "stripe",
    "payments":    "stripe",
    "saas":        "linear",
    "devtools":    "linear",
    "developer":   "linear",
    "infra":       "linear",
    "monitoring":  "linear",
    "docs":        "notion",
    "wiki":        "notion",
    "knowledge":   "notion",
    "content":     "notion",
    "blog":        "notion",
    "design":      "figma",
    "creative":    "figma",
    "studio":      "figma",
}


# Brief keyword → register hints. Keys are sets of keywords; if ANY keyword
# appears in the brief, the value is the register affinity. Earlier matches
# take precedence (more specific keywords listed first).
KEYWORD_REGISTER_HINTS: list[tuple[tuple[str, ...], RegisterName]] = [
    # HR / corporate admin → Workday
    (("leave management", "performance review", "compensation", "benefits enrollment",
      "human resources", "payroll", "headcount"), "workday"),

    # Finance / payments → Stripe
    (("invoice", "payment", "transaction", "ledger", "settlement", "treasury",
      "billing", "subscription", "revenue", "tax", "fraud"), "stripe"),

    # Dev tools / SaaS → Linear
    (("issue tracker", "bug tracking", "kanban", "sprint", "ci/cd", "deployment",
      "monitoring", "observability", "incident", "logs", "metrics dashboard",
      "kubernetes", "container"), "linear"),

    # Content / docs → Notion
    (("wiki", "documentation", "knowledge base", "blog", "publication", "article",
      "essay", "newsletter", "cms"), "notion"),

    # Design / creative → Figma
    (("design system", "brand guidelines", "moodboard", "asset library",
      "creative review", "portfolio"), "figma"),
]


def classify_register(brief: str, domain: str = "") -> RegisterName:
    """Pick a register from the brief + domain.

    Resolution order:
      1. Explicit domain match in DOMAIN_REGISTER_MAP
      2. Keyword hint in KEYWORD_REGISTER_HINTS
      3. Default to "workday" (broadest enterprise fallback)
    """
    brief_l = (brief or "").lower()
    domain_l = (domain or "").lower().strip()

    # Step 1: domain match
    if domain_l in DOMAIN_REGISTER_MAP:
        return DOMAIN_REGISTER_MAP[domain_l]

    # Step 2: keyword hints (most specific first)
    for keywords, register in KEYWORD_REGISTER_HINTS:
        if any(k in brief_l for k in keywords):
            return register

    # Step 3: default
    return "workday"


def list_registers() -> list[RegisterName]:
    """All available registers."""
    return ["default", "workday", "linear", "stripe", "notion", "figma"]


def describe_register(name: RegisterName) -> str:
    """Human-readable description for the editor / docs."""
    descriptions = {
        "default":  "neutral shadcn-default",
        "workday":  "corporate enterprise — dense data, navy primary, structured grays",
        "linear":   "monochrome neutral, sharp, single accent — SaaS / dev tools",
        "stripe":   "two-tone with gradient hero, layered shadows — fintech / payments",
        "notion":   "soft, airy, content-first — wikis / docs / knowledge bases",
        "figma":    "vibrant, friendly, playful — design tools / creative apps",
    }
    return descriptions.get(name, "unknown register")
```

### Step 2: Wire planner to use the new selector

Modify `backend/agents/planner.py`. Replace the inline `classify_register` from Wave 3 with a call to the new module:

```python
# backend/agents/planner.py — top
from services.register_selector import classify_register as _classify
# ... existing imports ...

# Replace the inline classify_register function with:
def classify_register(brief: str, domain: str = "") -> str:
    """Pick a stylistic register from the brief + domain.
    Delegates to services.register_selector for the canonical heuristics."""
    return _classify(brief, domain)
```

The router (`backend/routers/generate.py`) should already call `classify_register(brief, plan.get("domain", ""))` from Wave 3. No change needed there.

### Step 3: Add tests

```python
# backend/tests/services/test_register_selector.py — new
from services.register_selector import classify_register, list_registers, describe_register


def test_hr_domain_picks_workday():
    assert classify_register("manage employee leave", "hr") == "workday"


def test_fintech_brief_picks_stripe():
    assert classify_register("track customer invoices and payments", "") == "stripe"


def test_devtools_brief_picks_linear():
    assert classify_register("CI/CD dashboard with deployment logs", "") == "linear"


def test_docs_brief_picks_notion():
    assert classify_register("internal wiki for engineering documentation", "") == "notion"


def test_design_brief_picks_figma():
    assert classify_register("brand guidelines and asset library", "") == "figma"


def test_default_fallback_is_workday():
    assert classify_register("a simple notes app", "") == "workday"


def test_all_registers_listed():
    registers = list_registers()
    assert "workday" in registers
    assert "linear" in registers
    assert "stripe" in registers
    assert "notion" in registers
    assert "figma" in registers


def test_describe_register_returns_string_for_all():
    for r in list_registers():
        assert describe_register(r)
```

### Step 4: Run + commit

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_register_selector.py -v 2>&1 | tail -10
```

Expected: 8 PASS.

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/register_selector.py backend/tests/services/test_register_selector.py backend/agents/planner.py
git commit -m "feat(registers): domain × register intelligence with keyword + domain heuristics"
```

---

## Task 6: Editor manual register override

**Files:**
- Modify: `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`
- Modify: `backend/routers/_debug_schema.py` — endpoint to update design-spec.json

### Step 1: Backend endpoint to update register

Append to `backend/routers/_debug_schema.py`:

```python
from pydantic import BaseModel


class UpdateRegisterPayload(BaseModel):
    register: str


@router.put("/api/_debug/project-register/{short_id}")
async def update_project_register(short_id: str, payload: UpdateRegisterPayload):
    """Manual register override — updates design-spec.json's register field.
    Designer-only affordance for forcing a register choice."""
    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    spec_path = output_root / short_id / "src" / "contracts" / "design-spec.json"
    if not spec_path.exists():
        raise HTTPException(404, f"design-spec.json not found for {short_id}")

    valid_registers = {"default", "workday", "linear", "stripe", "notion", "figma"}
    if payload.register not in valid_registers:
        raise HTTPException(400, f"invalid register: {payload.register}")

    try:
        spec = json.loads(spec_path.read_text())
    except json.JSONDecodeError:
        raise HTTPException(500, "design-spec.json is corrupted")

    spec["register"] = payload.register
    spec_path.write_text(json.dumps(spec, indent=2))
    return {"register": payload.register, "ok": True}
```

### Step 2: Editor dropdown

In `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`, find the existing register badge (added in Wave 3 Task 11). Convert it from a static span to a click-to-open dropdown:

```tsx
const REGISTERS = ["default", "workday", "linear", "stripe", "notion", "figma"] as const;

const [registerMenuOpen, setRegisterMenuOpen] = useState(false);

async function handleRegisterChange(newRegister: string) {
  if (!project?.short_id) return;
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
  const r = await fetch(`${apiBase}/api/_debug/project-register/${project.short_id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ register: newRegister }),
  });
  if (r.ok) {
    setActiveRegister(newRegister);
    setRegisterMenuOpen(false);
    // Trigger a re-render of the preview tab if it's open
    queryClient?.invalidateQueries({ queryKey: ["render"] });
  }
}

// Replace static badge with:
<div className="relative">
  <button
    type="button"
    onClick={() => setRegisterMenuOpen((v) => !v)}
    className="rounded-full border border-border bg-muted/50 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-muted/80"
  >
    {activeRegister === "default" ? "default register" : `${activeRegister}-tier`} ▾
  </button>
  {registerMenuOpen && (
    <div className="absolute right-0 top-full mt-1 w-44 rounded-md border border-border bg-popover py-1 text-xs shadow-lg z-10">
      {REGISTERS.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => handleRegisterChange(r)}
          className={`block w-full text-left px-3 py-1.5 hover:bg-muted ${r === activeRegister ? "font-semibold" : ""}`}
        >
          {r === "default" ? "default" : `${r}-tier`}
        </button>
      ))}
    </div>
  )}
</div>
```

### Step 3: Verify + commit

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npx tsc --noEmit 2>&1 | head -10 || true

git add frontend/src/components/schema-editor/SchemaEditorPanel.tsx \
        backend/routers/_debug_schema.py
git commit -m "feat(editor): manual register override dropdown + backend update endpoint"
```

---

## Task 7: Final verification

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_register_selector.py tests/services/test_reference_bank.py tests/services/test_schema_prompt.py tests/integration/test_schema_migration.py -v 2>&1 | tail -10

cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-w4-final.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: all tests pass; 18/18 visual regression baselines unchanged.

---

## Self-review

### Spec coverage

| Spec section | Tasks |
|---|---|
| Linear-tier register | 1 |
| Stripe-tier register | 2 |
| Notion-tier register | 3 |
| Figma-tier register | 4 |
| Domain × register intelligence | 5 |
| Editor manual override | 6 |
| Final verification | 7 |

✓ All Phase 4 + Phase 5 register-related work covered. Phase 5 motion / archetype taxonomy / per-domain rubric / visual diff / cost dashboard / auto-promotion are in Wave 5.

### Type consistency

- `RegisterName` (defined in Wave 3) extends through Wave 4 — all 5 register names valid
- `RegisterBundle` shape unchanged from Wave 3 — every new bundle file uses the same structure
- `selectVariant(name, register)` — handles all 5 registers transparently
- `classify_register` — output is always a valid `RegisterName`

✓ Consistent.

---

## Out of scope (deferred to Wave 5)

- **Motion micro-interactions tied to motionLevel token** — Wave 5
- **Page-archetype taxonomy expansion** (workspace/console/inspector/wizard/audit-log/report) — Wave 5
- **Per-domain rubric weight tuning** — Wave 5
- **Critique-of-critique sanity pass** — Wave 5
- **Visual diff viewer in editor** — Wave 5
- **Cost dashboard UI** — Wave 5
- **Auto-promotion of high-scoring real generations** — Wave 5
- **Operational seeding for the 4 new registers** — manual, ~$80 ($20 × 4 registers) when ready
- **PageShell component variants** — deferred (only 3 components have variants per register; PageShell is in spec § Phase 3 but not load-bearing for the framework demonstration — can be added incrementally)
