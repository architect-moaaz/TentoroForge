# Design System Overhaul — Wave 3: Workday-tier Register

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Establish the register framework end-to-end and ship the first stylistic register (Workday-tier — corporate enterprise feel matching the apps we currently generate). After Wave 3, the planner picks Workday-tier for HR/admin domains, the schema agent emits register-aware schemas, components render with Workday-tier visual language (navy palette, tabular numerics, density.compact, elevation.bordered, radius.sharp), and the editor shows the active register.

**Architecture:** Register = a complete bundle of token values + (where needed) component variant code paths. The bundle is loaded via `TokensProvider` at the root of the rendered tree. Wave 2's token-consuming components automatically pivot to the register's values. Where token swaps aren't enough (e.g. Hero with breadcrumb above, MetricTile with sparkline below value), register-specific component variants kick in via a runtime selector. Reference bank gets re-seeded for Workday × {general, hr} × 5 page types.

**Tech Stack:** TypeScript / React 19 / Tailwind / Zod (existing). New: register selector module + Workday-specific component variant files. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-08-design-system-overhaul-design.md` § Phase 3.

---

## File structure

### New files

- `packages/library/src/theme/registers/index.ts` — register selector function + `RegisterName` type
- `packages/library/src/theme/registers/types.ts` — `RegisterBundle` interface
- `packages/library/src/theme/registers/workday.ts` — Workday token bundle
- `packages/library/src/components/Hero/Hero.workday.tsx` — register-aware Hero variant
- `packages/library/src/components/Card/Card.workday.tsx` — register-aware Card variant
- `packages/library/src/components/MetricTile/MetricTile.workday.tsx` — register-aware MetricTile variant
- `packages/library/src/components/PageShell/PageShell.tsx` — new component for sidebar nav + breadcrumb header (Workday-tier)
- `packages/library/src/components/PageShell/PageShell.workday.tsx`
- `packages/library/src/components/PageShell/PageShell.schema.ts`
- `packages/library/src/components/variants/index.ts` — runtime variant selector

### Modified files

- `packages/library/src/index.ts` — re-export registers + variant selector + PageShell
- `packages/library/src/theme/tokens-context.tsx` — `TokensProvider` accepts `register` and resolves the bundle
- `backend/agents/planner.py` — register classification
- `backend/agents/contract_agent.py` — write `register` into design-spec.json
- `backend/services/reference_bank.py` — lookup keyed on `(register, domain, page_type)` with fallback chain
- `backend/services/schema_prompt.py` — include active register in the prompt; load register-specific exemplars
- `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` — read register from design-spec, mount TokensProvider with the bundle
- `frontend/src/components/schema-editor/SchemaEditorPanel.tsx` — register badge in toolbar
- `packages/schema/src/nodes/foundation.ts` (or wherever the page-level schema lives) — the project-level meta object accepts an optional `register` field

---

## Task 1: Register types + selector

**Files:**
- Create: `packages/library/src/theme/registers/types.ts`
- Create: `packages/library/src/theme/registers/index.ts`

- [ ] **Step 1: types.ts**

```ts
// packages/library/src/theme/registers/types.ts
import type { defaultTokens } from "../default-tokens";

/** Names of all available registers. Each maps to a bundle file in this dir. */
export type RegisterName =
  | "default"
  | "workday"
  | "linear"
  | "stripe"
  | "notion"
  | "figma";

/**
 * A register is a partial override on top of defaultTokens. Whatever the
 * bundle DOESN'T specify falls through to the default value.
 *
 * Bundles can override:
 *   - color groups (primary/secondary/surface/border palettes)
 *   - typography family choices
 *   - density / elevation / motionLevel scalars
 *   - radius.scale
 */
export type RegisterBundle = {
  name: RegisterName;
  description: string;
  tokens: PartialDeep<typeof defaultTokens>;
};

type PartialDeep<T> = {
  [K in keyof T]?: T[K] extends object ? PartialDeep<T[K]> : T[K];
};
```

- [ ] **Step 2: index.ts**

```ts
// packages/library/src/theme/registers/index.ts
import type { RegisterBundle, RegisterName } from "./types";
import { defaultTokens } from "../default-tokens";
import { workdayRegister } from "./workday";

const REGISTRY: Partial<Record<RegisterName, RegisterBundle>> = {
  workday: workdayRegister,
};

/**
 * Return the bundle for a register name, or null for "default" / unknown.
 * Callers merge the bundle's tokens into defaultTokens to get the active set.
 */
export function getRegister(name: RegisterName | undefined): RegisterBundle | null {
  if (!name || name === "default") return null;
  return REGISTRY[name] ?? null;
}

/**
 * Deep-merge a register bundle's overrides on top of defaultTokens.
 * Returns a fresh token snapshot ready to feed into TokensProvider.
 */
export function resolveTokens(name: RegisterName | undefined): typeof defaultTokens {
  const bundle = getRegister(name);
  if (!bundle) return defaultTokens;
  return deepMerge(defaultTokens, bundle.tokens) as typeof defaultTokens;
}

function deepMerge<A extends object, B extends object>(a: A, b: B): A {
  const out: any = { ...a };
  for (const [k, v] of Object.entries(b)) {
    if (v !== null && typeof v === "object" && !Array.isArray(v) &&
        out[k] !== null && typeof out[k] === "object" && !Array.isArray(out[k])) {
      out[k] = deepMerge(out[k], v as any);
    } else {
      out[k] = v;
    }
  }
  return out;
}

export type { RegisterBundle, RegisterName };
export { workdayRegister } from "./workday";
```

- [ ] **Step 3: Re-export from library index**

In `packages/library/src/index.ts`, add:
```ts
export * from "./theme/registers";
```

- [ ] **Step 4: Commit**

Will land alongside Task 2 (workday bundle is what makes index.ts compile).

---

## Task 2: Workday token bundle

**Files:**
- Create: `packages/library/src/theme/registers/workday.ts`

- [ ] **Step 1: Implement workday.ts**

```ts
// packages/library/src/theme/registers/workday.ts
import type { RegisterBundle } from "./types";

/**
 * Workday-tier register — corporate enterprise feel.
 *
 * Visual language:
 *   - Navy primary, structured grays, muted accents
 *   - Density.compact: dense data tables, tight metric grids
 *   - Elevation.bordered: borders > shadows, structured cards
 *   - Radius.sharp (4px): rigid grid feel
 *   - Tabular numerics: aligned metric columns
 *   - Subtle motion: minimal animation
 *
 * Best for: HR, corporate admin, finance ops, compliance dashboards.
 */
export const workdayRegister: RegisterBundle = {
  name: "workday",
  description: "Corporate enterprise — dense, structured, navy-primary.",
  tokens: {
    color: {
      primary: {
        "50":  "#eff6ff", "100": "#dbeafe", "200": "#bfdbfe", "300": "#93c5fd",
        "400": "#60a5fa", "500": "#1d4ed8", "600": "#1e40af", "700": "#1e3a8a",
        "800": "#172554", "900": "#0f172a", "950": "#020617",
      },
      secondary: {
        "50":  "#f8fafc", "100": "#f1f5f9", "200": "#e2e8f0", "300": "#cbd5e1",
        "400": "#94a3b8", "500": "#64748b", "600": "#475569", "700": "#334155",
        "800": "#1e293b", "900": "#0f172a", "950": "#020617",
      },
      surface: { "0": "#ffffff", "1": "#f8fafc", "2": "#f1f5f9" },
      border:  { default: "#cbd5e1" },
      muted:   { default: "#94a3b8" },
      text:    { primary: "#0f172a", secondary: "#475569", tertiary: "#94a3b8" },
      sidebar: { bg: "#0f172a", text: "#cbd5e1", active: "#1e40af" },
    },
    typography: {
      font:   { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
      display:  { family: "Inter, system-ui, sans-serif", weight: 700 },
      bodyText: { family: "Inter, system-ui, sans-serif", weight: 400, lineHeight: 1.45 },
      numeric:  { family: "ui-monospace, SFMono-Regular, monospace", weight: 600, tabular: true },
      scaleMode: "tight",
    },
    radius: { scale: "sharp" },
    density: "compact",
    elevation: "bordered",
    motionLevel: "subtle",
  },
};
```

- [ ] **Step 2: Commit Tasks 1 + 2 together**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/theme/registers/ packages/library/src/index.ts
git commit -m "feat(registers): register selector framework + Workday-tier token bundle"
```

- [ ] **Step 3: Verify build**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -20 || true
```

Expected: clean.

---

## Task 3: TokensProvider accepts a register

**Files:**
- Modify: `packages/library/src/theme/tokens-context.tsx`

- [ ] **Step 1: Update Provider signature**

```tsx
// inside packages/library/src/theme/tokens-context.tsx

import { resolveTokens, type RegisterName } from "./registers";

export function TokensProvider({
  tokens,
  register,
  children,
}: {
  tokens?: Partial<typeof defaultTokens>;
  register?: RegisterName;       // ← NEW
  children: React.ReactNode;
}) {
  const merged = React.useMemo(() => {
    const base = resolveTokens(register);   // start from register bundle (or defaults)
    if (!tokens) return base;
    // Merge ad-hoc overrides on top
    return { ...base, ...tokens } as typeof defaultTokens;
  }, [tokens, register]);
  return <TokensContext.Provider value={merged}>{children}</TokensContext.Provider>;
}
```

- [ ] **Step 2: Verify**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -20 || true

cd frontend && npm run dev -- -p 6501 > /tmp/frontend-w3.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 18/18 PASS — the playground doesn't mount the Provider with a register, so defaults still apply.

- [ ] **Step 3: Commit**

```bash
git add packages/library/src/theme/tokens-context.tsx
git commit -m "feat(tokens): TokensProvider accepts register name + resolves bundle"
```

---

## Task 4: Workday-aware MetricTile variant

**Files:**
- Create: `packages/library/src/components/MetricTile/MetricTile.workday.tsx`

- [ ] **Step 1: Implement Workday MetricTile**

The Workday-register MetricTile differs from the default in:
- Smaller, denser tile (matches density.compact)
- Hard navy border (no shadow — matches elevation.bordered + radius.sharp)
- Tabular numeric value with bigger weight contrast
- Status sparkline below value (when trend present) gets stronger treatment
- Hover-state navy accent on the left edge

```tsx
// packages/library/src/components/MetricTile/MetricTile.workday.tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface WorkdayMetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

const TILE = "relative flex flex-col gap-1.5 border-l-4 border-l-primary border border-border bg-card px-5 py-4 text-card-foreground transition-colors";
const LABEL = "text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground";
const VALUE = "text-2xl font-bold leading-none tracking-tight tabular-nums text-foreground";
const DELTA = "inline-flex items-center gap-1 text-[11px] font-semibold tabular-nums";

const DELTA_GLYPH = { up: "▲", down: "▼", flat: "—" } as const;
const DELTA_TONE: Record<"up"|"down"|"flat", string> = {
  up:   "text-emerald-700",
  down: "text-red-700",
  flat: "text-muted-foreground",
};

function fmtValue(v: number | string, format: MetricTilePropsType["format"]): string {
  if (typeof v === "string") return v;
  if (format === "currency") return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);
  if (format === "percent")  return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 0 }).format(v);
  if (format === "duration") return `${v}s`;
  return new Intl.NumberFormat("en-US").format(v);
}

function fmtDelta(v: number): string {
  return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 0, signDisplay: "never" }).format(Math.abs(v));
}

export function MetricTileWorkday({ label, value, format, delta, trend, style }: WorkdayMetricTileProps) {
  return (
    <div className={TILE} style={resolveStyle(style)} {...useMotion(style?.motion)}>
      <p className={LABEL}>{label}</p>
      <p className={VALUE}>{fmtValue(value, format)}</p>
      {delta && (
        <span className={`${DELTA} ${DELTA_TONE[delta.direction]}`} data-delta-direction={delta.direction}>
          <span aria-hidden="true">{DELTA_GLYPH[delta.direction]}</span>
          <span>{fmtDelta(delta.value)}</span>
        </span>
      )}
      {trend && trend.length > 0 && (
        <svg className="mt-1 h-6 w-full text-muted-foreground/70" viewBox={`0 0 ${trend.length * 10} 24`} preserveAspectRatio="none" aria-hidden="true">
          <polyline fill="none" stroke="currentColor" strokeWidth="1.5"
            points={trend.map((v, i) => {
              const max = Math.max(...trend, 1);
              return `${i * 10},${24 - (v / max) * 22}`;
            }).join(" ")} />
        </svg>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit (with Tasks 5+6+7)**

This task pairs with Tasks 5-7 (Card variant + Hero variant + variant selector). Single commit at end of Task 7.

---

## Task 5: Workday-aware Card variant

**Files:**
- Create: `packages/library/src/components/Card/Card.workday.tsx`

```tsx
// packages/library/src/components/Card/Card.workday.tsx
import * as React from "react";
import type { CardProps } from "./Card";
import { resolveStyle } from "../../style/resolveStyle";

const CARD = "border border-border bg-card text-card-foreground transition-colors hover:border-primary/40";
const TITLE = "border-b border-border px-5 py-3 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground";
const BODY = "px-5 py-4";
const FOOTER = "border-t border-border px-5 py-3";

export function CardWorkday({ title, footer, children, style }: CardProps) {
  return (
    <div className={CARD} style={resolveStyle(style)}>
      {title && <div className={TITLE}>{title}</div>}
      <div className={BODY}>{children}</div>
      {footer && <div className={FOOTER}>{footer}</div>}
    </div>
  );
}
```

NOTE: read the existing `Card.tsx` to confirm `CardProps` matches. If the existing component uses a different prop name for the title slot (e.g. `header` instead of `title`), align with that — the variant must accept the same props as the default Card.

---

## Task 6: Workday-aware Hero variant

**Files:**
- Create: `packages/library/src/components/Hero/Hero.workday.tsx`

```tsx
// packages/library/src/components/Hero/Hero.workday.tsx
import * as React from "react";
import type { HeroProps } from "./Hero";
import { resolveStyle } from "../../style/resolveStyle";

const HERO = "border-b border-border bg-surface-1 px-8 pt-8 pb-6";
const EYEBROW = "text-[11px] font-semibold uppercase tracking-[0.1em] text-primary mb-2";
const HEADLINE = "text-3xl font-bold leading-tight tracking-tight text-foreground";
const SUBHEAD = "mt-2 text-sm text-muted-foreground max-w-2xl";
const CTAS = "mt-5 flex items-center gap-3";

export function HeroWorkday({ eyebrow, headline, subhead, ctas, children, style }: HeroProps) {
  return (
    <header className={HERO} style={resolveStyle(style)}>
      {eyebrow && <p className={EYEBROW}>{eyebrow}</p>}
      <h1 className={HEADLINE}>{headline}</h1>
      {subhead && <p className={SUBHEAD}>{subhead}</p>}
      {ctas && ctas.length > 0 && (
        <div className={CTAS}>
          {ctas.map((cta, i) => (
            <button key={i} type="button" className="h-9 px-4 text-sm font-medium border border-border bg-card hover:bg-primary hover:text-primary-foreground hover:border-primary transition-colors">
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

NOTE: read the existing `Hero.tsx` for the actual HeroProps shape. The CTA action wiring must match — if the existing Hero uses `onCta` callback or schema-driven dispatch, mirror that here.

---

## Task 7: Variant selector + barrel

**Files:**
- Create: `packages/library/src/components/variants/index.ts`

- [ ] **Step 1: Implement variant selector**

```ts
// packages/library/src/components/variants/index.ts
import * as React from "react";

import { MetricTile } from "../MetricTile/MetricTile";
import { MetricTileWorkday } from "../MetricTile/MetricTile.workday";
import { Card } from "../Card/Card";
import { CardWorkday } from "../Card/Card.workday";
import { Hero } from "../Hero/Hero";
import { HeroWorkday } from "../Hero/Hero.workday";

import type { RegisterName } from "../../theme/registers";

/**
 * Runtime variant selector. Returns the register-specific variant for a
 * component, or the default when no variant exists.
 *
 * Usage in registry: `register("MetricTile", selectVariant("MetricTile", activeRegister))`.
 *
 * Variants are opt-in — components without entries here always use the default.
 */
const VARIANTS: Record<string, Partial<Record<RegisterName, React.ComponentType<any>>>> = {
  MetricTile: { workday: MetricTileWorkday },
  Card:       { workday: CardWorkday },
  Hero:       { workday: HeroWorkday },
};

const DEFAULTS: Record<string, React.ComponentType<any>> = {
  MetricTile, Card, Hero,
};

export function selectVariant(name: string, register: RegisterName | undefined): React.ComponentType<any> {
  if (!register || register === "default") return DEFAULTS[name] ?? (DEFAULTS as any)[name];
  return VARIANTS[name]?.[register] ?? DEFAULTS[name];
}
```

- [ ] **Step 2: Re-export from library index**

```ts
// packages/library/src/index.ts — add:
export * from "./components/variants";
```

- [ ] **Step 3: Commit Tasks 4+5+6+7 together**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/{MetricTile,Card,Hero}/*.workday.tsx \
        packages/library/src/components/variants/ \
        packages/library/src/index.ts
git commit -m "feat(registers): Workday variants for MetricTile/Card/Hero + variant selector"
```

- [ ] **Step 4: Verify build + visual regression**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -20 || true

cd frontend && npm run dev -- -p 6501 > /tmp/frontend-w3-variants.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 18/18 PASS — the playground doesn't use the variant selector, so all defaults apply.

---

## Task 8: Planner agent picks a register

**Files:**
- Modify: `backend/agents/planner.py`

- [ ] **Step 1: Add register classification logic**

Find where `planner.py` builds its output. Add a register classification step. v1 = rule-based heuristic, no extra LLM call:

```python
def classify_register(brief: str, domain: str) -> str:
    """Pick a stylistic register from the project brief.

    v1 — rule-based. Future versions can use a small classifier LLM call.
    Default = "workday" for now since it's the only seeded register.
    """
    brief_l = brief.lower()
    domain_l = (domain or "").lower()

    # HR / leave / corporate-admin / finance-ops → Workday
    HR_KEYWORDS = ("leave", "hr ", "human resource", "payroll", "performance review",
                    "benefits", "compliance", "audit", "policy")
    FINTECH_KEYWORDS = ("ledger", "invoice", "payment", "transaction", "trading",
                         "portfolio", "compliance", "settlement")
    DEV_TOOLS_KEYWORDS = ("repo", "deploy", "ci/cd", "issue tracker", "incident",
                           "monitoring", "logs")
    CONTENT_KEYWORDS = ("wiki", "docs", "knowledge base", "blog", "cms")

    if domain_l in ("hr", "healthcare", "fintech"):
        return "workday"
    if any(k in brief_l for k in HR_KEYWORDS + FINTECH_KEYWORDS):
        return "workday"
    if any(k in brief_l for k in DEV_TOOLS_KEYWORDS):
        return "linear"  # not seeded yet; falls back to default in renderer
    if any(k in brief_l for k in CONTENT_KEYWORDS):
        return "notion"  # not seeded yet
    return "workday"   # default while only Workday is shipped
```

Wire `classify_register` into the planner output — add `register` to the `app-model.json` shape (top-level field).

- [ ] **Step 2: Commit**

```bash
git add backend/agents/planner.py
git commit -m "feat(planner): classify register from brief + domain (v1 rule-based)"
```

---

## Task 9: design-spec.json + reference_bank carry register

**Files:**
- Modify: `backend/agents/contract_agent.py` (or wherever design-spec is written)
- Modify: `backend/services/reference_bank.py` — lookup keyed on register

- [ ] **Step 1: contract_agent writes register**

Find where `design-spec.json` is created. Read the planner's `app-model.json` for the `register` field and include it in the design-spec output:

```python
design_spec = {
    "register": plan.get("register", "workday"),
    "palette": ...,  # existing
    # ...
}
```

- [ ] **Step 2: reference_bank lookup with register**

Modify `services/reference_bank.py`. The current `load_exemplars(domain, page_type, limit)` should gain a register parameter:

```python
def load_exemplars(
    domain: str,
    page_type: str,
    *,
    register: str = "default",
    limit: int = 2,
) -> list[Exemplar]:
    """Resolution order:
      1. backend/reference_pages/<register>/<domain>/<page_type>/
      2. backend/reference_pages/<register>/general/<page_type>/
      3. backend/reference_pages/default/<domain>/<page_type>/
      4. backend/reference_pages/default/general/<page_type>/
      5. (legacy paths from Phase 14 — backend/reference_pages/<domain>/<page_type>/)
      6. empty
    """
    paths = [
        _BANK_ROOT / register / domain / page_type,
        _BANK_ROOT / register / "general" / page_type,
        _BANK_ROOT / "default" / domain / page_type,
        _BANK_ROOT / "default" / "general" / page_type,
        _BANK_ROOT / domain / page_type,        # legacy
        _BANK_ROOT / "general" / page_type,     # legacy
    ]
    for cell in paths:
        if cell.exists():
            # ... existing exemplar loading from this cell ...
            if exemplars:
                return exemplars[:limit]
    return []
```

NOTE: read the existing `reference_bank.py` and adapt — preserve the existing single-domain lookup as a fallback so legacy pre-Wave-3 banks still work.

- [ ] **Step 3: schema_prompt passes register**

Find where `build_schema_prompt` calls `load_exemplars`. Add `register` to the call:

```python
register = (registry or {}).get("design_spec", {}).get("register", "default")
exemplars = load_exemplars(domain=domain, page_type=page_type, register=register, limit=2)
```

- [ ] **Step 4: Commit**

```bash
git add backend/agents/contract_agent.py backend/services/reference_bank.py backend/services/schema_prompt.py
git commit -m "feat(registers): design-spec carries register; reference bank lookup keyed on register"
```

---

## Task 10: Render-scaffold mounts TokensProvider with register

**Files:**
- Modify: `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx`

- [ ] **Step 1: Read register from design-spec, mount TokensProvider**

Find the existing `page.tsx` route. It already loads schemas + tokens + builds the registry. Add register loading:

```tsx
// Existing token load:
const tokens = await loadTokens(projectRoot);

// NEW: load design-spec for register
import { promises as fs } from "node:fs";
import path from "node:path";

async function loadRegister(projectRoot: string): Promise<string> {
  try {
    const text = await fs.readFile(
      path.join(projectRoot, "src", "contracts", "design-spec.json"),
      "utf8",
    );
    const spec = JSON.parse(text);
    return spec.register || "default";
  } catch {
    return "default";
  }
}

const register = await loadRegister(projectRoot);

// Wrap render in TokensProvider:
import { TokensProvider } from "@tentoroforge/library";

return (
  <main style={tokenCssVars} data-project-id={projectId} data-page-path={pagePath} data-register={register}>
    <TokensProvider register={register as any} tokens={tokens as any}>
      <SchemaRenderer page={page} dataEngine={noopDataEngine} registry={registry} />
      <A11yTreeEmbed tree={a11yTree} />
    </TokensProvider>
  </main>
);
```

- [ ] **Step 2: Use variant selector when registering components**

Where the registry is built (`buildRegistry()` in the same file), use `selectVariant`:

```tsx
import { selectVariant } from "@tentoroforge/library";

// Replace these lines:
//   reg("MetricTile", MetricTile, MetricTileProps, "static");
//   reg("Card", Card, CardProps, "static", true);
//   reg("Hero", Hero, HeroProps, "layout", true);
// With:
const MetricTileVariant = selectVariant("MetricTile", register as any);
const CardVariant = selectVariant("Card", register as any);
const HeroVariant = selectVariant("Hero", register as any);

reg("MetricTile", MetricTileVariant, MetricTileProps, "static");
reg("Card", CardVariant, CardProps, "static", true);
reg("Hero", HeroVariant, HeroProps, "layout", true);
```

- [ ] **Step 3: Verify scaffold renders with the register**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
lsof -ti:6503 | xargs kill -9 2>/dev/null || true
cd apps/render-scaffold && npm run dev > /tmp/scaffold-w3.log 2>&1 &
sleep 10

# Find a project with a design-spec.json that has a register
for proj in $(ls /Users/m/Work/code/poc/design2ui-forge-v3/output 2>/dev/null | head -5); do
  if [ -f "/Users/m/Work/code/poc/design2ui-forge-v3/output/$proj/src/contracts/design-spec.json" ]; then
    echo "$proj has design-spec"
    grep -o '"register"[^,}]*' "/Users/m/Work/code/poc/design2ui-forge-v3/output/$proj/src/contracts/design-spec.json" || echo "  (no register field — pre-W3)"
  fi
done

# Test render of any existing project (will use default register since none have W3 register yet)
PROJ=$(ls /Users/m/Work/code/poc/design2ui-forge-v3/output | head -1)
[ -n "$PROJ" ] && curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:6503/p/$PROJ/"

lsof -ti:6503 | xargs kill -9 2>/dev/null || true
```

Expected: 200 — scaffold boots cleanly. Existing projects render with default register (no `register` field in their design-spec yet).

- [ ] **Step 4: Commit**

```bash
git add apps/render-scaffold/src/app/p/\[projectId\]/\[...slug\]/page.tsx
git commit -m "feat(scaffold): mount TokensProvider with register; use variant selector"
```

---

## Task 11: Editor register badge

**Files:**
- Modify: `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`

- [ ] **Step 1: Add register badge to toolbar**

Find SchemaEditorPanel.tsx. Read the design-spec.json for the active project (or grab the register from already-loaded project state if available):

```tsx
const [activeRegister, setActiveRegister] = useState<string>("default");
useEffect(() => {
  if (!project?.short_id) return;
  // Read design-spec from the project files API
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
  fetch(`${apiBase}/api/_debug/project-file/${project.short_id}/src/contracts/design-spec.json`)
    .then((r) => (r.ok ? r.json() : {}))
    .then((spec) => setActiveRegister(spec?.register || "default"))
    .catch(() => setActiveRegister("default"));
}, [project?.short_id]);
```

If a `/api/_debug/project-file/...` endpoint doesn't exist, you can either:
- Add a small one in `backend/routers/_debug_schema.py` that serves arbitrary JSON files from `output/<id>/`
- Or read from the existing project metadata API if it already includes design-spec content

In the toolbar JSX, add:

```tsx
<span className="rounded-full border border-border bg-muted/50 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
  {activeRegister === "default" ? "default register" : `${activeRegister}-tier`}
</span>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/schema-editor/SchemaEditorPanel.tsx
# also commit the backend endpoint if you added one
git commit -m "feat(editor): register badge in toolbar shows active design register"
```

NOTE: this task is NICE TO HAVE. If reading design-spec from the editor requires non-trivial plumbing, mark it DONE_WITH_CONCERNS — the register info is in design-spec.json regardless, and a follow-up plan can add the badge.

---

## Task 12: Reference bank re-seed for Workday (OPERATIONAL — deferred)

The seeder script (`backend/scripts/seed_reference_bank.py`) needs an extra `--register` flag and lookup change so it writes to `backend/reference_pages/workday/<domain>/<page_type>/`.

This task SHIPS THE CODE for the seeder change. Actually RUNNING the seeder requires:
- Live ANTHROPIC_API_KEY
- Live render-service + scaffold
- ~$20 in LLM calls for 10 cells × 2 exemplars
- ~30 minutes wall time

The user runs it manually after this plan ships. Plan only ships the code change.

- [ ] **Step 1: Add register flag to seeder**

```python
# backend/scripts/seed_reference_bank.py — modify _parse_args + seed_cell

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", default="default", choices=["default", "workday", "linear", "stripe", "notion", "figma"])
    # ... existing args ...

# In _persist_exemplar, change the cell path:
def _persist_exemplar(*, register, domain, page_type, idx, ...):
    cell = _BANK_ROOT / register / domain / page_type
    # ... rest unchanged ...

# In seed_cell, accept register parameter and pass to _persist_exemplar
async def seed_cell(*, register, domain, page_type, target_count, max_attempts, seeder_version):
    # ...
```

The brief sent to the LLM should ALSO mention the register:

```python
def _build_seeder_prompt(register: str, domain: str, page_type: str) -> str:
    register_descriptions = {
        "workday": "corporate enterprise, dense data tables, navy primary, structured grays, status pills heavy",
        "default": "neutral shadcn-default visual register",
        # ...
    }
    return f"""You are designing a top-tier exemplar Page schema for the Tentoroforge platform reference bank.

VISUAL REGISTER: {register} — {register_descriptions.get(register, "default visual register")}
DOMAIN: {domain}
PAGE TYPE: {page_type}

# ... rest ...
"""
```

- [ ] **Step 2: Update README / runbook**

Append to `docs/render-service.md`:

```markdown
### Re-seeding for a new register

```bash
cd backend
for D in general healthcare fintech hr; do
  for T in list detail form dashboard settings; do
    python -m scripts.seed_reference_bank \
      --register workday --domain "$D" --page-type "$T" \
      --target-count 2 --max-attempts 8 --seeder-version v1
  done
done
git add backend/reference_pages/workday/
git commit -m "feat(reference-bank): seed Workday-tier exemplars (v1)"
```

Cost: ~$20 one-time per register.
```

- [ ] **Step 3: Commit code change**

```bash
git add backend/scripts/seed_reference_bank.py docs/render-service.md
git commit -m "feat(seeder): support --register flag for register-keyed reference banks"
```

---

## Self-review

### Spec coverage

| Spec section | Tasks |
|---|---|
| Register types + selector | 1 |
| Workday token bundle | 2 |
| TokensProvider register-aware | 3 |
| Workday component variants | 4, 5, 6 |
| Variant selector | 7 |
| Planner register classification | 8 |
| design-spec + reference bank wiring | 9 |
| Render-scaffold mounts register | 10 |
| Editor badge | 11 |
| Seeder code update + runbook | 12 |

✓ All Phase 3 spec items covered.

### Type consistency

- `RegisterName` defined in `packages/library/src/theme/registers/types.ts`, used everywhere
- `RegisterBundle` interface drives the bundle file shape
- `selectVariant(name, register)` used by both render-scaffold and (future) other consumers
- `register` field flows: planner → app-model.json → contract_agent → design-spec.json → render-scaffold → TokensProvider

✓ Consistent.

### Backward compatibility

- Existing projects without a `register` field in design-spec → `loadRegister` returns "default" → `TokensProvider` resolves to defaultTokens → today's appearance preserved
- Existing schemas don't mention any new register-aware props → variant selector falls back to defaults → today's appearance
- 18/18 visual regression baselines remain stable

✓ No regressions.

---

## Out of scope (deferred to Wave 4 / 5)

- **Linear / Stripe / Notion / Figma registers** — Wave 4
- **Domain × register intelligence table** — Wave 4 (planner currently uses simple keyword heuristics)
- **Editor manual register override** — Wave 4 (editor only displays, doesn't switch)
- **A/B fidelity comparison across registers** — Wave 4
- **Auto-promotion of high-scoring real generations into the bank** — Wave 5
- **Operational running of the seeder** — user-triggered, ~$20 in LLM costs
