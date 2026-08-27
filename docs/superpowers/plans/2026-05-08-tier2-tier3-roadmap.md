# Tier 2 + Tier 3 Roadmap — Wave Breakdown

**Spec:** `docs/superpowers/specs/2026-05-08-enterprise-depth-design.md`

This is a roadmap document, not a detailed plan. Each wave below has a task count + brief task summaries + file-touch sketch. Detailed plans get written wave-by-wave as work proceeds (one was already written for Tier 2 Wave 1: `2026-05-08-tier2-wave1-component-batch1.md`).

This roadmap is the source of truth for sequencing. Detailed plans inherit dependencies + scope from here.

---

## Tier 2 — Functionally Workday-grade

### Tier 2 Wave 1 — Component batch 1 (DETAILED PLAN EXISTS)

Plan: `docs/superpowers/plans/2026-05-08-tier2-wave1-component-batch1.md`

```
9 tasks
~10-12 days, 1 engineer

Components: Chart (line/bar/area) + Sparkline + DataGrid (v1) + Timeline
Touches:    packages/schema/src/nodes/{charts,data-display}.ts
            packages/library/src/components/{Chart,Sparkline,DataGrid,Timeline}/
            apps/render-scaffold + apps/visual-regression
            backend/services/schema_prompt.py
New deps:   recharts, @tanstack/react-virtual
```

### Tier 2 Wave 2 — Component batch 2

```
~10 tasks
~10-12 days, 1 engineer

Components:
  1. ApprovalStepper        Horizontal stepper for multi-stage approval flows.
                            Status enum: pending | current | approved | rejected | skipped.
                            Click-to-jump-to-step where applicable.

  2. PersonCard             Avatar + name + role + manager + status combined.
                            Used in sidebars, employee detail pages.

  3. FilterBar              Saved filters dropdown, smart defaults, bulk-operations
                            surface. Persists state in URL.

  4. CommandPalette         Cmd-K modal with fuzzy-search across actions/schemas/pages.
                            Power-user affordance.

  5. ActivityFeed           Audit-trail sidebar — chronological list of actor/action/
                            target/timestamp. Project-wide (different from Timeline).

Files (per component):
  packages/schema/src/nodes/<group>.ts          (zod node)
  packages/library/src/components/<Name>/       (3-5 files: tsx + schema.ts + variants.ts)
  apps/render-scaffold/.../page.tsx             (registry entry)
  frontend/.../component-playground/            (playground entry)
  apps/visual-regression/tests/                 (baseline)

Modified:
  backend/services/schema_prompt.py             (component contracts + anti-patterns)

No new deps required (FilterBar uses existing Select; CommandPalette uses fuzzysort
or kbar — pick during implementation; ActivityFeed reuses Timeline primitives).

Tasks per component: ~2 (component implementation + playground/baseline).
Plus 1 task each for: NodeV2 wiring, schema_prompt update, migration verify.
```

### Tier 2 Wave 3 — Component batch 3

```
~6 tasks
~6-8 days, 1 engineer

Components:
  1. EmptyStateRich         Illustration + heading + body + primary CTA + sample-data link.
                            Replaces basic EmptyState for first-render contexts.
                            Uses domain-specific illustrations (Tier 3 Wave 5 will replace
                            generic placeholder art with branded set).

  2. DateRangePicker        Calendar popover + presets (last 7d / 30d / quarter-to-date / etc).
                            Reporting-filter primitive.

  3. MultiSelect            Checkbox-list dropdown for bulk operations + filter values.
                            Used inside FilterBar and stand-alone.

Same pattern as Wave 2. ~2 tasks per component.

Plus 1 task: schema_prompt + migration verify.

Optional dep: react-day-picker for DateRangePicker. Can roll our own with native
<input type="date"> for first version; upgrade later.
```

### Tier 2 Wave 4 — Layout primitives

```
~7 tasks
~5-7 days, 1 engineer

Components:
  1. AppShell                  Sidebar + topbar + main + right rail composition.
                               Schema-driven slot mapping.
                               Replaces ad-hoc per-page page-shell wrapping.

  2. InspectorPanel            Slide-out detail view from the right edge.
                               For "click row → see full detail" without page change.
                               Backed by URL state so deep-link works.

  3. TabPanelWithDeepLink      URL-aware tabs. Tab state survives refresh + back-button.
                               Replaces (or augments) existing Tabs/TabPanel for
                               cases where tab-state needs persistence.

Files:
  Same pattern as Waves 1-3. AppShell is a layout primitive (can wrap any page);
  InspectorPanel + TabPanelWithDeepLink are interactive widgets.

Tasks: ~2 per component + URL-state plumbing helper (1 task: useUrlState hook).
+ NodeV2 wiring + schema_prompt + verify (3 tasks).

No new deps. URL state via Next.js useSearchParams + useRouter.
```

### Tier 2 Wave 5 — Engine richness (workflow + data)

```
~10 tasks
~10-12 days, 1 engineer

Workflow engine extensions:
  1. Multi-stage approval with PARALLEL approvers
     (current: serial only. New: any-of, all-of stage compositions)
  2. Conditional routing
     (e.g. escalate-if-amount > $X)
  3. Delegation rules
     (out-of-office redirects to backup approver)
  4. Reminder + escalation hooks
     (after-N-days send-reminder; after-M-days escalate)
  5. Audit-log entry per state transition
     (consumed by Timeline component from Wave 1)

Files:
  backend/templates/runtime/workflows/{engine,types}.ts
  backend/services/workflow-validator.py
  backend/services/runtime_injector.py (existing — extend for new constructs)
  Tests across both Python + TypeScript sides.

Data engine extensions:
  6. Aggregations: sum / avg / count / by-group queries
  7. Joins / nested queries
     ("Employee with their team's recent activity")
  8. Saved views with URL persistence
     (consumed by FilterBar from Wave 2)
  9. Server-side pagination + infinite scroll (>1000 rows scenarios)

Files:
  backend/templates/runtime/data-engine.ts
  backend/services/data-engine-* (new helpers)

Plus 1 task: doc updates + migration verify.
```

### Tier 2 Wave 6 — Schema patterns + reference bank re-seed

```
~6 tasks
~5-7 days, 1 engineer + ~$100 LLM cost

Tasks:
  1. Gold-example schemas (enterprise patterns)
     backend/services/schema_examples/enterprise/
       master-detail.json
       multi-step-wizard.json
       approval-flow.json
       reporting-dashboard.json
       settings-grouped.json
       audit-log.json

  2. schema_prompt teaches WHEN to use each pattern by archetype

  3. Re-seed reference bank for ALL 5 registers using new components
     (the bank from Wave 4 doesn't include DataGrid, Chart, Timeline patterns yet)
     5 registers × 4 domains × 5 page-types × 2 = 200 exemplars
     Cost: ~$100 (LLM + render). Run via existing seeder with --seeder-version=v2.

  4. Update describe_register descriptions in register_selector to include
     Tier 2 component preferences ("workday tier uses DataGrid heavily,
     Linear-tier uses Chart line+sparkline combo")

  5. Update gold examples in backend/services/schema_examples/{detail,list}/
     to demonstrate Tier 2 components in the v1 archetype contexts

  6. End-to-end verification: regenerate one project per register, confirm
     fidelity scores improve over pre-Wave-6 baseline.

Outcome: schema agent now produces schemas that USE the new components.
Without this wave, the new components exist but are unused by generations.
```

---

## Tier 3 — Genuinely matches Workday

### Tier 3 Wave 1 — Domain data libraries (HR-deep first)

```
~10 tasks
~10-15 days, 1 engineer

Tasks:
  1. HR job-title taxonomy
     backend/fixtures/hr/_taxonomies/job-titles.json
     (50+ realistic titles across Engineering/Product/Design/HR/Sales/etc.)

  2. HR department hierarchies
     backend/fixtures/hr/_taxonomies/departments.json
     (4-5 levels deep, real company structure)

  3. Leave-type enums + accrual rates
     backend/fixtures/hr/_taxonomies/leave-types.json
     (vacation: 15d/yr accrue 1.25/mo; sick: unlimited;
      bereavement: 3d/occurrence; jury-duty: as-needed; etc.)

  4. Performance-rating scales + rubric anchors
     backend/fixtures/hr/_taxonomies/performance-ratings.json

  5. Benefit-package definitions
     backend/fixtures/hr/_taxonomies/benefits.json
     (health/dental/vision/401k/wellness/equity)

  6. Realistic data relationships generator
     backend/services/fixtures/relationship_gen.py
     (employees with manager chains 4-5 levels deep)
     (leave balances with accrual events + carryover history)

  7. Persona-aware copy per role
     backend/services/copy/hr_personas.py
     ("Direct Reports" vs "My Team" vs "Teammates" — same field, 3 audiences)

  8. Healthcare domain — medium-depth (mirrors HR-deep approach)
     backend/fixtures/healthcare/_taxonomies/{conditions,procedures,specialities}.json

  9. Fintech domain — medium-depth
     backend/fixtures/fintech/_taxonomies/{transaction-types,account-types,...}.json

 10. Verification + docs
     Run a few real generations across domains; confirm copy + data feels
     realistic. Document in docs/domain-libraries.md.
```

### Tier 3 Wave 2 — Accessibility audit + remediation

```
~12 tasks
~10-15 days, 1 engineer

Setup:
  1. Add axe-core to apps/visual-regression
     npm install --save-dev @axe-core/playwright
  2. New test file: apps/visual-regression/tests/a11y.spec.ts
     One test per playground component, runs axe.run() and asserts no violations

Per-component remediation (one task each, batched):
  3. Form components — Input/Textarea/Select/DatePicker/Checkbox/Form
     Associate <label> + aria-describedby + aria-invalid + role attributes

  4. Interactive components — Button/IconButton/Link/NavLink
     aria-label for icon-only; ensure focus-visible ring

  5. Modal/Dialog components — ConfirmDialog/Toast/CommandPalette/InspectorPanel
     aria-modal, focus trap (focus-trap-react), focus restore on close

  6. Tabs/Accordion/Breadcrumb
     ARIA roles (tab/tablist/tabpanel) + arrow-key navigation
     aria-expanded for accordion items
     aria-current for breadcrumb current

  7. DataGrid
     role="grid", aria-rowindex, aria-colindex, aria-sort
     Live-region announcement for sort/filter/row-count changes

  8. Chart + Sparkline
     aria-label + role="img" for the SVG
     Data-table fallback for screen readers (visually hidden)

  9. Color contrast verification per register
     Add a script: scripts/verify-contrast.ts
     Runs through every (color, color) pair in each register's tokens
     Asserts WCAG AA (4.5:1 for body, 3:1 for large text)

 10. Keyboard nav testing
     Add keyboard-nav tests to a11y.spec.ts
     Verify tab-order matches DOM-order for each playground section

 11. Live-region announcements
     Add an `<div role="status" aria-live="polite">` to render-scaffold
     Wire SchemaRenderer to announce via this region for dynamic content

 12. PR check + docs
     CI gate: a11y.spec.ts must pass on PR
     docs/a11y.md with the pattern catalog
```

### Tier 3 Wave 3 — Responsive design

```
~12 tasks
~12-15 days, 1 engineer

Token system:
  1. Add breakpoints to token-types.ts
     export type Breakpoint = "mobile" | "tablet" | "desktop"
  2. Each register's tokens get breakpoint-aware density:
     workday: { density: { mobile: spacious, tablet: comfortable, desktop: compact } }

useDensity / useElevation hooks become viewport-aware:
  3. Add useBreakpoint() hook reading window.matchMedia
  4. useDensity returns density[currentBreakpoint] when token is breakpoint-keyed

Mobile component variants (highest-traffic patterns):
  5. AppShell.mobile — bottom-nav for primary actions + slide-up sheet for secondary
  6. DataGrid.mobile — card-list layout with swipe-actions instead of <table>
  7. Form.mobile — full-screen step-by-step instead of multi-section scroll
  8. InspectorPanel.mobile — full-screen modal instead of slide-out
  9. FilterBar.mobile — bottom sheet for filter management

Mobile-first schema patterns:
 10. Add gold examples in schema_examples/mobile-first/
     Documenting common patterns where mobile structure differs

Render-scaffold:
 11. Capture screenshots at 3 breakpoints (mobile 375 / tablet 768 / desktop 1280)
     Vision evaluator scores all 3
     Fidelity log carries per-viewport scores

 12. Verification + docs
     A few real projects re-rendered at all 3 breakpoints; manual review.
     docs/responsive.md with the pattern catalog.
```

### Tier 3 Wave 4 — Performance

```
~8 tasks
~8-10 days, 1 engineer

Component-level:
  1. DataGrid virtualisation already in Wave 1 v1.
     Wave 4 task: extend to support column-virtualisation for >50 cols.
  2. Lazy-load Chart, OrgChart, CommandPalette via React.lazy + Suspense
  3. Skeleton states match real content layout (not generic boxes)
     Audit each loading state per register; refactor to match the actual
     component's structure

Generated app:
  4. Code-splitting per route (Next.js default — verify it works for our pages)
  5. Prefetch on link hover (Next.js Link prefetch behaviour, tune defaults)
  6. Image optimisation in PersonCard / EmptyStateRich / Hero images
     Use next/image; set explicit width + height; lazy-load offscreen

Bundle monitoring:
  7. bundle-analyzer report per build
     Add `pnpm bundle:analyze` script to packages/library + frontend
  8. PR comment with bundle delta
     GitHub Action: compare main vs PR bundle size; comment on PR
     Hard-fail when > 5% growth without justification (label override)
```

### Tier 3 Wave 5 — Iconography + illustrations

```
~6 tasks
~5-10 days (mostly design work, not code-heavy)

This wave is primarily creative work + integration. Code is minimal — most
effort is sourcing or commissioning the assets.

  1. Icon set audit
     Catalogue every Lucide icon currently used in the library.
     Identify ~30-40 most-used icons that need branded variants per register.

  2. Sourcing decision
     Either: license a paid set (Streamline / Phosphor Pro / Storyset) +
     adapt to register palettes
     Or: commission custom set from a designer
     Or: hybrid (license most + custom for register-defining 5-10 icons)
     Budget: $200-2000

  3. Icon component
     New component: <Icon name="..." />
     Reads useRegister() to pick the right variant
     Falls back to Lucide for icons not in branded set

  4. Empty-state illustrations
     Per-domain: HR (empty calendar / empty inbox);
                  fintech (empty ledger / no transactions);
                  healthcare (empty schedule / no patients);
                  content (empty docs / no articles);
                  design (empty canvas / no projects)
     5 domains × ~5 illustrations each = 25 illustrations
     Source: Storyset / unDraw / commission

  5. Onboarding artwork
     First-render screens (after generation completes, before user has data)
     Per-domain hero illustrations

  6. 404/500 error illustrations
     Branded per register

Outcome: replaces "generic Lucide aesthetic" with a per-register branded
visual language. Significant perception lift.
```

### Tier 3 Wave 6 — Telemetry-driven iteration

```
~8 tasks
Ongoing — initial setup ~5 days, then steady-state

This wave is about turning the production fidelity-loop output into a
self-improving feedback signal for the system.

Setup:
  1. Daily aggregation script
     backend/scripts/aggregate_fidelity_telemetry.py
     Reads all output/*/src/contracts/fidelity-log.json
     Aggregates: pass-rate per register × domain × page-type, lowest-scoring
     issue axes, patch-acceptance trends.
     Writes to backend/telemetry/daily-{date}.json

  2. Pattern bucketing classifier
     Categorise critique JSON entries into:
       - "missing component" (LLM tried to use X but it doesn't exist)
       - "wrong register" (planner picked Linear; brief screams Workday)
       - "bad copy" (generic / wrong-tone)
     Use a classifier LLM call on the critique text.

Iteration loops:
  3. Patch-agent prompt evolution
     Track patch-acceptance rate week-over-week.
     Refine PATCH_AGENT_SYSTEM_PROMPT based on common rejection reasons.
     Maintain CHANGELOG.md per prompt version.

  4. Schema-agent prompt evolution
     Same as patch-agent: track failure modes, refine.

Reference bank growth:
  5. Auto-promotion already shipped (Wave 5 Task 7).
     New work: weekly review queue UI at /admin/bank-candidates
     Lists candidates; reviewer clicks promote/reject.
     Promote → calls promote_candidate() helper; reject → marks dismissed.

  6. Bank version bumps
     When seeder prompts evolve, bump version, re-seed worst cells first
     (worst = lowest avg fidelity score in production for that cell).

Visibility:
  7. Cost dashboard already shipped (Wave 5 Task 6).
     Extension: register × domain × page-type breakdowns.

  8. Per-domain rubric weight tuning loop
     compute_composite_for_domain function exists from Wave 5 Task 3.
     Wire it in vision_evaluator/evaluator.py.
     Track which domains have systematic score-axis biases; tune weights
     per-quarter based on telemetry.
```

---

## Cross-tier ongoing concerns

These thread through every wave (Tier 1, 2, and 3):

- **Visual regression suite** — every new component / variant gets a baseline immediately. Never let drift accumulate.
- **Schema migration corpus** — every notable real generation captured. Token / component changes can't break existing schemas silently.
- **Reference bank versioning** — `seeder_version` field. Bump version when prompts change. Re-seed worst cells first.
- **Documentation per phase** — docs/components/<name>.md, docs/registers.md, docs/tokens.md, docs/a11y.md, docs/responsive.md, docs/domain-libraries.md, docs/perf.md, docs/iconography.md.

---

## Execution sequencing recommendation

### Realistic 6-month plan (one engineer)

```
Month 1: Tier 2 Wave 1 (component batch 1) — Chart + DataGrid + Sparkline + Timeline
Month 2: Tier 2 Wave 2 (batch 2) — ApprovalStepper + PersonCard + FilterBar + CommandPalette + ActivityFeed
Month 2-3: Tier 2 Wave 3 (batch 3) + Wave 4 (layout primitives)
Month 3: Tier 2 Wave 5 (engine richness) + Wave 6 (re-seed bank)
Month 4: Tier 3 Wave 1 (HR domain data) + Wave 5 (iconography sourcing)
Month 5: Tier 3 Wave 2 (a11y) + Wave 3 (responsive) — interleave
Month 6: Tier 3 Wave 4 (performance) + Wave 5 finalisation + Wave 6 setup
```

### Two-engineer parallel (~3 months total)

Eng A: Tier 2 Waves 1-6 (component depth)
Eng B: Tier 3 Wave 1 (data libraries — independent of Tier 2 components)

Once Tier 2 is shipped, both engineers converge on Tier 3 Waves 2-6.

### MVP 6-week sub-roadmap (if "make ONE demo Workday-grade")

```
Weeks 1-2: Tier 2 Wave 1 (Chart + DataGrid + Sparkline + Timeline)
Week 3:    Tier 2 Wave 2 partial (ApprovalStepper + PersonCard only)
Week 4:    Tier 2 Wave 4 (AppShell + InspectorPanel only — skip TabPanelWithDeepLink)
Week 5:    Tier 2 Wave 6 (schema patterns + re-seed Workday register only)
Week 6:    Tier 3 Wave 1 partial (HR domain libraries only)
```

After 6 weeks: a generated leave-management app would have a real Workday-tier appearance + DataGrid/Chart/Timeline + InspectorPanel for drill-in + HR-realistic data. That's a Workday-grade demo for one domain.

---

## Dependency map (load-bearing only)

```
Tier 2 Wave 1   →   provides components used by Wave 4 (Inspector mounts DataGrid)
                →   provides Sparkline used by Wave 2 (PersonCard inset)
                →   prerequisite for Wave 6 schema patterns (need components to exist)

Tier 2 Wave 2   →   ActivityFeed depends on Timeline from Wave 1
                →   FilterBar uses MultiSelect from Wave 3 (or rolls its own first)

Tier 2 Wave 6   →   prerequisite for Tier 3 Wave 1 (data libraries fill in
                    realistic content for the new components)

Tier 3 Wave 2   →   independent — can start anytime after Tier 1 (components
                    audited as they ship; new components in Tier 2 audited
                    as they land in Wave 2-3)

Tier 3 Wave 3   →   depends on Wave 2 partial (need a11y patterns for mobile too)

Tier 3 Wave 4   →   independent — performance work doesn't gate on others

Tier 3 Wave 5   →   independent (creative work) — can run in parallel with code work

Tier 3 Wave 6   →   prerequisite: at least 50 production generations with
                    fidelity-log data. Realistically Month 3+.
```

---

## What this roadmap does NOT prescribe

- **Exact dep choices** (Recharts vs Visx; react-day-picker vs custom; kbar vs cmdk vs roll-own) — implementation plan picks
- **Pixel-exact token values** for breakpoint-keyed densities — Tier 3 Wave 3 tunes based on real device testing
- **Iconography licensing** — design + budget call, made when Wave 5 starts
- **Hosting / deployment of generated apps** — out of scope; each customer hosts their own
- **Multi-tenant primitives, RBAC, SSO, i18n, telemetry** — explicit out-of-scope per spec

---

## What's needed to start Tier 2 Wave 1 right now

```
1. Anthropic API key (already in env from Wave 1-3 work)
2. npm install (already done)
3. Visual regression suite operational (already done)
4. Decision: how to schedule the work — single session via subagent-driven-
   development (~1 day in agent-time), or multiple sessions
```

The detailed Wave 1 plan at `docs/superpowers/plans/2026-05-08-tier2-wave1-component-batch1.md` is ready to execute.
