# Design System Overhaul — Design Spec

**Date:** 2026-05-08
**Status:** Design approved (per chat ideation), pending implementation
**Levers:** Information hierarchy primitives + Token system expansion + Stylistic registers
**Predecessors:**
- `2026-05-06-fidelity-render-loop-design.md` (Phase 12.5 + 13) — shipped
- `2026-05-06-domain-aware-fidelity-loop-design.md` (Phase 14 + 15) — shipped

---

## Goal

Lift generated UI quality from "competent shadcn baseline" to "enterprise-grade visual craft" by giving the design system three things it currently lacks: information hierarchy primitives that components can express, a token system that drives layout (not just color), and 5 stylistic registers (Workday / Linear / Stripe / Notion / Figma) the planner picks per project so the visual register matches the domain.

## Why this is needed

The fidelity loop (Phase 14) can score "looks bad" and emit patches, but it can't push beyond what the system can render. Today the renderer flattens everything to "shadcn defaults with custom colors" — fonts are hard-coded, density is fixed, elevation/depth doesn't exist as a concept, and component visual weight is identical regardless of importance. Without these primitives, no amount of LLM intelligence will produce enterprise-tier output.

Real-world symptom: a generated leave-balance detail page renders as four equal-sized MetricTiles touching with no gaps, generic shadcn rounded-md cards, single sans-serif throughout, no breadcrumbs, no tabs, KV labels and metric labels using identical typography. The structural problem is not the LLM — it's the system.

## Locked design decisions (from chat ideation)

| | Decision |
|---|---|
| **Hierarchy primitives** | `importance: primary\|secondary\|tertiary` on MetricTile; `role` on Hero/Section; `density` on Card; `weight` on Heading |
| **Token expansion** | Add `density`, `elevation`, `radius.scale`, `typography.display\|body\|numeric`, `typography.scale`, `motion` token groups |
| **Register count** | 5 — Workday / Linear / Stripe / Notion / Figma |
| **First register** | Workday-tier (matches current corporate-admin generation patterns) |
| **Register selection** | Planner agent picks one per project from a heuristic table |
| **Backward compatibility** | All new component props optional; all token additions have defaults that preserve today's appearance |
| **Test infrastructure** | Playwright visual regression suite stood up before component refactor begins |
| **Standardization pattern** | CVA (class-variance-authority) becomes canonical for variant-bearing components |
| **Reference bank scope** | Bank keyed on `(register, domain, page_type)`; full bank = 5 × 4 × 5 × 2 = 200 exemplars |
| **Rollout** | 5 implementation waves; each wave ships independently with visible quality lift |

## Phased rollout

```
Wave 1 — Phase 0 + Phase 1     ~16 tasks   Foundation + Hierarchy
Wave 2 — Phase 2               ~24 tasks   Token system expansion
Wave 3 — Phase 3               ~12 tasks   Workday-tier register
Wave 4 — Phase 4 + Phase 5     ~20 tasks   Remaining 4 registers
Wave 5 — Phase 6               ~7 tasks    Polish + motion + observability

Total: ~79 tasks over ~14 weeks (one engineer) or ~7-9 weeks (two engineers in parallel)
```

---

## Phase 0 — Foundation

Prerequisites for safely refactoring 38 library components. Without these, regressions accumulate silently.

### What gets built

- **Visual regression test infrastructure** — Playwright-driven screenshot diffing in a dedicated test app under `apps/visual-regression/`. Every library component captured in known states (default + each variant). Baseline image set committed. PR diff workflow detects regressions.
- **Component token-consumption audit** — written analysis of how each of the 38 components currently consumes tokens (Tailwind class string vs inline style vs class-name conditional). Output: `docs/component-token-audit.md` with a normalization plan ranking components by refactor complexity.
- **CVA standardization scaffolding** — `class-variance-authority` adopted as the canonical pattern for components with variants. One example refactor (Button.tsx) sets the template; subsequent components follow.
- **Schema-migration test fixture** — `backend/tests/integration/test_schema_migration.py` loads ~20 real LLM-generated schemas captured from `output/`. Asserts they render without errors after each token-system change. Critical safety net.
- **Component playground in editor** — `frontend/src/app/(dev-only)/component-playground/page.tsx` renders every library component in every variant on a single page. Used for visual diffing during development.

### Why Phase 0 exists

Touching 38 components without these guardrails is the single biggest risk in the overhaul. Layouts will break in subtle ways (a Card's padding regresses by 2px, a Hero's headline weight changes from 600 to 500). Without baseline screenshots, no one notices until the render-scaffold is already shipping the regression to vision-evaluator scoring.

### Effort: ~5 days, 5 tasks.

---

## Phase 1 — Information Hierarchy primitives (Lever 3)

Cheapest lever. Largely independent of Phase 2 — can run in parallel.

### What gets built

New optional props across ~10 components:

```ts
MetricTile  importance: "primary" | "secondary" | "tertiary"   // primary = 2x size, big tabular numeric
Hero        role:       "headline" | "banner" | "inline"        // headline = full bleed; inline = one-liner above content
Section     role:       "headline" | "content" | "aside" | "footer"
Card        density:    "tight" | "regular" | "loose"
Heading     weight:     "light" | "regular" | "bold" | "display" // display unlocks future display-font slot
```

All new props are **optional with sensible defaults that match today's appearance** — existing schemas keep working.

### Component-level visual scaling

Per importance/role, components scale visual weight:

```
MetricTile.importance:
  primary    → 2x size, heavy numeric weight, prominent delta, larger padding
  secondary  → 1x (today's appearance)
  tertiary   → 0.75x, label-first layout, no delta

Section.role:
  headline   → top page header padding (3rem above, 1.5rem below), border-bottom
  content    → today's appearance
  aside      → narrower, softer background, smaller padding
  footer     → muted text, top border, smaller everything
```

### Schema-agent integration

`backend/services/schema_prompt.py` updated to teach the LLM hierarchy semantics:
- "Exactly one MetricTile per page should be `importance: primary`"
- "Hero on a list page is `role: inline`; Hero on a detail page is `role: headline`"
- "The four equal-tile pattern is an anti-pattern — pick one primary"

Patch agent at `backend/agents/patch_agent.py` reasons about hierarchy in its critique loop.

Gold-example schemas at `backend/services/schema_examples/` updated to demonstrate good importance/role/density choices, so the schema agent has concrete patterns to imitate.

### Effort: ~7 days, 11 tasks.

---

## Phase 2 — Token system expansion (Lever 2)

The structural change. Touches every library component. Phase 0 is hard prerequisite.

### Token shape today (rough)

```ts
{
  color:      { primary, secondary, accent, surface, border, ... },
  spacing:    { 0..64, semantic: { page, card, section, ... } },
  radius:     { sm, md, lg, xl, full },
  shadow:     { sm, md, lg, xl },
  typography: { font, weight, scale, paragraph },
}
```

### Token shape after Phase 2

```ts
{
  color:      { ...today, no changes },
  spacing:    { ...today, no changes },
  radius:     { ...today + scale: "sharp" | "soft" | "round" },
  shadow:     { ...today, no changes },
  typography: {
    display:  { family, weight, scale },          // headlines, hero text
    body:     { family, weight, lineHeight },     // paragraphs, labels
    numeric:  { family, weight, tabular: bool },  // metric values, table cells
    scale:    "tight" | "balanced" | "dramatic",  // H1→H6 size jump
  },
  density:    "compact" | "comfortable" | "spacious",  // drives Stack/Section/Card gap defaults
  elevation:  "flat" | "bordered" | "layered" | "floating",  // Card/Hero/MetricTile shadow + border treatment
  motion:     "none" | "subtle" | "expressive",     // FadeIn/Stagger envelope
}
```

### What gets built

**Token schema + compiler (3-4 days, 5 tasks):**
- `packages/library/src/theme/token-types.ts` — TS types for the expanded shape
- `packages/library/src/theme/default-tokens.ts` — defaults that preserve today's appearance
- `packages/renderer/src/runtime/tokens.ts` — `compileTokens` extended to emit new CSS variables
- `packages/library/src/theme/tokens-context.tsx` — React provider so components read active values via `useTokens()` hook
- Token compiler tests asserting each group emits the expected CSS variables

**Component refactor in 4 batches (10-12 days, ~14 tasks):**

```
Batch 1 — Layout primitives (4-5 days)
  Stack       reads density.gap
  Section     reads density.padding + elevation
  Split + Sidebar + Cluster   read density.gap
  Card        reads elevation + radius.scale + density.padding
  Hero        reads typography.scale + density.padding

Batch 2 — Data display (3-4 days)
  MetricTile  reads typography.numeric + elevation
  Heading     reads typography.display + typography.scale + weight tokens
  Badge + Avatar + KeyValueList   read radius.scale + density
  Table       reads density.row-height + elevation

Batch 3 — Forms (3-4 days)
  Input + Textarea + Select + DatePicker + Checkbox   read radius.scale + density.input-height
  Form        reads density.field-gap

Batch 4 — Feedback + nav (2-3 days)
  Skeleton + Alert + EmptyState + LoadingState        read radius.scale + elevation
  Tabs + Accordion + Breadcrumb                       read density.gap + radius.scale
```

Each batch follows the CVA template from Phase 0 (Button.tsx). Visual regression suite catches any unintended shift.

**Schema-agent + editor integration (2 days, 3 tasks):**
- `services/schema_prompt.py` token-paths block auto-includes density/elevation/etc. (the LLM sees they exist as bindable tokens)
- Editor Style tab in `frontend/src/components/schema-editor/PropertiesPanel/` gains selectors for the new groups
- Editor density/elevation preview switch — designer can preview the page in different settings without persisting

**Migration + testing (1-2 days, 3 tasks):**
- Run schema-migration corpus (Phase 0.4) against new components — assert no rendering errors
- Re-baseline visual regression suite — capture new defaults
- Render-scaffold + editor preview parity check — same schema renders identically in both

### Effort: ~15 days, 24 tasks.

---

## Phase 3 — First register: Workday-tier (Lever 1)

Workday-tier picked first because it matches the current generation patterns (HR / corporate admin). Establishes the register framework end-to-end.

### What is a register

A register is a complete bundle of token values + (where needed) component variant code paths. It represents a coherent design "personality":

| Register | Defining traits |
|---|---|
| **Workday** | Navy primary, structured grays, tabular numerics, density.compact, elevation.bordered, radius.sharp, motion.subtle. Traditional enterprise feel — dense data tables, status pills heavy, rigid grid. |
| **Linear** | Monochrome neutral, single accent, mono numerics, density.compact, elevation.flat, radius.sharp (4px). Sharp, dense, technical SaaS feel. |
| **Stripe** | Two-tone palette with gradient hero, structured cards, density.comfortable, elevation.layered, radius.soft. Financial confidence; data-grid prominent. |
| **Notion** | Soft grays, density.spacious, elevation.flat, radius.round (12px), generous line-height. Content-first, airy, no shadows. |
| **Figma** | Vibrant palette, friendly numerics, density.comfortable, elevation.floating, radius.round. Playful, designer-tone, generous color use. |

### What gets built for Workday

- `packages/library/src/theme/registers/index.ts` — register selector function (name → token bundle)
- `packages/library/src/theme/registers/workday.ts` — Workday token bundle (full color palette, font choices, spacing tuning)
- 4 register-aware component variants in `packages/library/src/components/<X>/<X>.workday.tsx`:
  - Hero — left-aligned, breadcrumb above, status pill in corner
  - Card — bordered, no shadow, navy accent strip on hover
  - MetricTile — bordered tile, tabular numeric, sparkline below value
  - Page-shell — sidebar nav, breadcrumb header, page-action toolbar
- `packages/library/src/components/variants/index.ts` — runtime selects variant by active register; falls back to default component when no variant exists
- `backend/agents/planner.py` — register classification logic (rule-based v1; "leave management" → Workday)
- `backend/agents/contract_agent.py` — `register: "workday"` written into design-spec.json
- `backend/services/reference_bank.py` — lookup keyed on `(register, domain, page_type)` with fallback chain
- Reference bank re-seed for Workday × {general, hr} × 5 page types = 10 cells × 2 exemplars = 20 exemplars (~$20)
- Editor — register badge in toolbar showing active register

### Effort: ~10 days, 12 tasks.

---

## Phase 4 — Second register (1.5 weeks)

Pick Linear or Stripe based on which domain comes up next in real generations. Linear-tier for SaaS/developer-tools; Stripe-tier for fintech.

### What gets built

- Register token bundle (1.5d)
- Register-aware Hero + MetricTile + Page-shell variants (2d)
- Planner classification rules expand (0.5d)
- Reference bank re-seed (1d operational)
- A/B fidelity comparison: same project under both registers, compare scores (0.5d)

### Effort: ~5 days, 7 tasks.

---

## Phase 5 — Remaining 3 registers (3 weeks)

Notion-tier, the remaining one from {Linear, Stripe}, and Figma-tier. Each is roughly 1 week.

### Per-register pattern

```
Day 1-1.5  Token bundle (palette, typography, density tuning)
Day 2-3    Hero + Card + Section variants (where token-only differences aren't enough)
Day 4      Re-seed bank (~10 cells × 2 exemplars)
Day 5      A/B comparison; identify gaps; document register strengths/weaknesses
```

### Plus domain × register intelligence (3 days, 4 tasks)

- `backend/services/register_selector.py` — domain × register mapping table (e.g. fintech → Stripe; HR → Workday; design-tools → Figma)
- Planner uses the mapping; falls back to a small classifier when domain is ambiguous
- Editor — manual register override for designers (triggers re-render of all pages)
- A/B fidelity dashboard — `/api/_debug/fidelity-stats` segmented by register

### Effort: ~13 days, 13 tasks.

---

## Phase 6 — Polish, motion, observability (2 weeks)

Production-grade quality work. Can start any time after Phase 3 lands.

### What gets built

- Motion token-driven micro-interactions (Stagger, FadeIn already exist; wire to motion token; subtle in Workday, expressive in Figma, none in plain) — 2d
- Page-archetype taxonomy expansion: `workspace`, `console`, `inspector`, `wizard`, `audit-log`, `report` — 2d
- Per-domain rubric weight tuning (fintech weights `domainFeel` higher; HR weights `informationDensity` higher) — 1d
- Critique-of-critique sanity pass (second model evaluates rubric application consistency) — 1d
- Editor visual diff viewer — side-by-side iter-N vs iter-(N-1) screenshots with patch overlay — 2d
- Cost dashboard UI in `frontend/src/app/admin/fidelity-cost.tsx` — 1d
- Auto-promotion of high-scoring real generations into the bank — pages scoring ≥ 8.5 land in `bank-candidates/` queue with weekly review UI — 2d

### Effort: ~11 days, 7 tasks.

---

## Cross-phase ongoing concerns

These thread through every wave:

- **Visual regression suite kept current** — every PR re-baselines affected components; main branch is the source of truth for "expected appearance"
- **Schema migration corpus grows** — every notable real generation goes into the test fixture so future token changes can't break it silently
- **Reference-bank version-bumping** — when seeder prompts change, bump `seeder_version`; re-seed worst-scoring cells first
- **Documentation evolves per phase** — `docs/render-service.md`, new `docs/registers.md`, new `docs/tokens.md`

## Success criteria

The overhaul succeeds when, on a representative test suite of 10 generated projects:

- **Median fidelity composite ≥ 8.5** (vs. ~7.0 baseline today)
- **All four equal-tile anti-pattern is gone** — no page emits 3+ MetricTiles at the same `importance` level
- **Register-correctness ≥ 90%** — the planner picks the "correct" register (per human review) on 9 of 10 projects
- **Visual regression suite catches all unintended changes** — no token/component edit ships without being captured in baseline screenshots
- **Patch acceptance rate stays ≥ 80%** — the patch agent's success rate doesn't degrade as the system grows in complexity
- **Per-register cost stays ≤ $2 median** — adding registers doesn't blow up the LLM cost shape

## Dependencies

- **Predecessor plans shipped:** ✓ Phase 12.5+13 (render-service, vision evaluator), ✓ Phase 14+15 (closed loop, reference bank)
- **CVA library** (`class-variance-authority`) — new dep for `packages/library/`
- **Playwright** — already a backend dep from Phase 13; needs frontend setup for visual regression
- **No new backend Python deps** — all changes use existing libraries

## Out of scope (deferred to future plans)

- **Per-page register override** — letting the user mix registers within a single project
- **User-authored custom registers** — beyond the 5 provided
- **Animated transitions between registers** — switching register currently triggers a full re-render
- **Theme inheritance / register stacking** — registers don't compose
- **Register-specific component additions** — e.g. a Workday-only `OrgChart` component
- **Mobile-first register variants** — registers are desktop-tuned; mobile responsiveness is per-component
- **Dark mode** — every register today is light-mode; dark mode is a future axis
