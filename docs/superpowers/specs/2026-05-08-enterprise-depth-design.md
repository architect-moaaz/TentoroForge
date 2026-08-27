# Enterprise Depth — Tier 2 + Tier 3 Design Spec

**Date:** 2026-05-08
**Status:** Design draft, pending implementation plans
**Predecessors:**
- `2026-05-06-fidelity-render-loop-design.md` (Phase 12.5 + 13) — shipped
- `2026-05-06-domain-aware-fidelity-loop-design.md` (Phase 14 + 15) — shipped
- `2026-05-08-design-system-overhaul-design.md` (Tier 1 — Levers 1+2+3) — shipped

---

## Goal

Move generated apps from "looks like Workday" to "functions and feels like Workday." Tier 1 (just shipped) gave the visual register; Tier 2 closes the functional/component-vocabulary gap; Tier 3 brings the system to a quality bar where it would survive a real-customer audit.

The two tiers are sequenced because Tier 3 work depends on knowing what's painful in real Tier 2 use — accessibility/responsive/performance issues are best identified after the new components ship and get exercised.

## Why this is needed

Tier 1 shipped the design framework. Re-generating the leave-management app now produces a Workday-tier visual register: navy palette, bordered cards, tabular numerics, sharp radius, breadcrumbed page header. That's the perceptual lift.

The functional gap remains: a real Workday leave-management page has a DataGrid (frozen header, sortable, filter bar, group-by, bulk actions, status pills inline), a Chart of accrual-over-time, a Timeline of approval history, a PersonCard sidebar with manager + approver chain. The current library has Table (basic), no Chart, no Timeline, no PersonCard. The schema agent CAN'T compose enterprise patterns when the parts don't exist.

Tier 3 gap is broader: today's components don't survive accessibility audit (no ARIA labels on most interactive elements, focus order undefined, screen-reader announcements missing). They don't have mobile variants (designed desktop-first). They don't lazy-load or virtualise. Real customers stuck with these in production would file P0 bugs within a week.

## Locked design decisions (per chat ideation)

| | Decision |
|---|---|
| **Scope split** | Tier 2 = component depth (~5-8 weeks). Tier 3 = quality bar (~3-6 months). |
| **Tier 2 ordering** | Components first → primitives → engines → schema patterns. The LLM can't use what doesn't exist; build vocabulary before training. |
| **Tier 3 ordering** | Domain data → accessibility → responsive → performance → iconography. Research is ongoing across all. |
| **Component priorities** | DataGrid + Chart + Sparkline + Timeline are highest leverage (~80% of "looks Workday" by themselves). |
| **Backward compatibility** | Every new component is additive; existing schemas unaffected. New components opt-in via the schema agent's prompt update. |
| **Reference bank** | Re-seed with Tier-2-aware exemplars after components land. Without re-seeding, the LLM has no concrete examples of the new patterns. |
| **Telemetry-driven** | Use the fidelity loop + critique-meta-eval to identify which Tier 2 components are most missed in real generations; prioritise based on data, not opinion. |

## Tier 2 — Functionally Workday-grade

### What gets built

**Theme A — Missing components (~12 new) — 3-4 weeks**

The component vocabulary the LLM needs to compose enterprise patterns:

```
DataGrid          frozen header + columns; row-virtualisation for >100 rows;
                  sortable; bulk-select; row-actions menu; filter bar slot;
                  group-by; expand-row for nested detail; saved views via URL.
                  Replaces basic Table for data-heavy contexts; Table stays
                  for simple cases.

Chart             Three sub-types: LineChart, BarChart, AreaChart.
                  Driven by a single `<Chart type="line" data={...}>` API.
                  Token-aware (uses primary colour for the series).
                  Uses an existing chart lib (Recharts most likely — already
                  in the npm registry, MIT license, React-native).

Sparkline         Inline mini-chart for use inside DataGrid cells, MetricTile
                  trends, dashboard rows. No axes, no tooltips — just shape.

Timeline          Vertical timeline with dot markers; for audit logs and
                  approval-history visualisation. Each entry has timestamp +
                  actor + status + optional details slot.

ApprovalStepper   Horizontal stepper showing multi-stage approval flow.
                  Each step has status (pending / current / approved / rejected
                  / skipped). Click-to-jump-to-step when applicable.

PersonCard        Avatar + name + role + manager + status combined.
                  Used in sidebars + employee detail pages.

OrgChart          Hierarchical visualisation, draggable to rearrange.
                  Lower priority — only matters for HR domain. May ship
                  as Tier 2.5 if it slips.

FilterBar         Saved filters dropdown, smart defaults, bulk-operations
                  surface. Persists current filter state in the URL.

CommandPalette    Cmd-K modal with fuzzy-search across actions, schemas,
                  pages. Power-user affordance; significantly lifts perceived
                  sophistication.

ActivityFeed      Audit-trail sidebar — chronological list with actor +
                  action + target + timestamp. Different from Timeline
                  (Timeline is per-entity history; ActivityFeed is project-wide).

EmptyStateRich    Illustration + heading + body + primary CTA + sample-data
                  link. Replaces basic EmptyState for first-render contexts.

DateRangePicker   Reporting-filter primitive — calendar popover + presets
                  (last 7d / last 30d / quarter-to-date / etc.).

MultiSelect       Checkbox-list dropdown for bulk operations + filter values.
```

Each new component:
- Has a Zod schema in `packages/schema/src/nodes/`
- Is exported from `packages/library/src/components/<Name>/`
- Has CVA variants where applicable (per Tier 1 pattern)
- Reads tokens via `useDensity`/`useElevation`/`useTokens` (per Tier 1)
- Has Workday + at least one other register variant (Linear or Stripe most likely)
- Has Playwright visual regression coverage in the playground

**Theme B — Layout primitives (~3 new) — 1 week**

```
AppShell          Sidebar + topbar + main + right rail composition.
                  Standard enterprise app shell. Schema-driven slot mapping.

InspectorPanel    Slide-out detail view from the right edge.
                  For "click a row → see full detail" without page change.

TabPanelWithDeepLink  URL-aware tabs. Tab state survives refresh,
                  back-button works correctly.
```

**Theme C — Engine richness — 1-2 weeks**

```
Workflow engine extensions:
  - Multi-stage approval with PARALLEL approvers (currently serial only)
  - Conditional routing (escalate-if-amount-over-X)
  - Delegation rules (out-of-office redirects to backup)
  - Reminder + escalation hooks (after-N-days send-reminder)
  - Audit-log entry per state transition (consumed by Timeline component)

Data engine extensions:
  - Aggregations (sum / avg / count by-group)
  - Joins / nested queries ("Employee with their team")
  - Saved views with URL persistence
  - Server-side pagination + infinite scroll for >1000 rows
```

**Theme D — Schema patterns / templates — 1 week**

Gold-example schemas demonstrating enterprise patterns the LLM should imitate:

```
backend/services/schema_examples/
  enterprise/
    master-detail.json       — DataGrid + InspectorPanel nesting
    multi-step-wizard.json   — Form across 3-5 steps with ApprovalStepper progress
    approval-flow.json       — DataGrid of pending requests + Timeline of history
    reporting-dashboard.json — FilterBar + Chart + DataGrid + export
    settings-grouped.json    — Side-nav + grouped Form sections
    audit-log.json           — ActivityFeed + Timeline + filter
```

Schema agent's prompt teaches WHEN to use each pattern based on the page-archetype.

### Tier 2 success criteria

- Median fidelity composite score on HR/admin projects ≥ 8.7 (vs. current 8.0-ish)
- Generated DataGrid usage ≥ 80% on detail/list pages where data tables make sense
- Chart usage ≥ 60% on dashboard pages
- Reference bank re-seeded with at least one exemplar per (register, archetype) cell that uses ≥ 2 new components

### Tier 2 implementation waves

```
Tier 2 Wave 1 — Component batch 1: Chart + Sparkline + DataGrid + Timeline       (~10 tasks)
Tier 2 Wave 2 — Component batch 2: ApprovalStepper + PersonCard + FilterBar +
                                    CommandPalette + ActivityFeed                 (~10 tasks)
Tier 2 Wave 3 — Component batch 3: EmptyStateRich + DateRangePicker + MultiSelect (~6 tasks)
Tier 2 Wave 4 — Layout primitives: AppShell + InspectorPanel + TabPanelWithDeepLink (~7 tasks)
Tier 2 Wave 5 — Engine richness: workflow + data engine extensions                (~10 tasks)
Tier 2 Wave 6 — Schema patterns + reference bank re-seed                          (~6 tasks)

Total: ~49 tasks, ~5-8 weeks (1 engineer) or ~3-4 weeks (2 engineers parallel)
```

OrgChart is excluded from the main waves; ships as Tier 2.5 if HR domain customers explicitly need it.

## Tier 3 — Genuinely matches Workday

### What gets built

**Theme E — Domain-specific data libraries — 3 weeks**

Today's fixtures in `backend/fixtures/<domain>/<entity>.json` are skeletal — 10 records, generic shape. Real Workday-grade demos need:

```
HR vocabulary banks:
  - 50+ realistic job titles per department (Engineering Manager → Senior
    Engineer → Engineer → Junior Engineer; HR Director → HR Business Partner →
    HR Generalist; etc.)
  - Department hierarchies that match real companies (Engineering > Platform >
    Infrastructure; Engineering > Product; Engineering > Quality)
  - Leave-type enums with realistic accrual rates and carryover policies
    (vacation 15d/yr accrue 1.25/mo; sick unlimited; bereavement 3d per occurrence)
  - Performance-rating scales with rubric anchors (5 = top performer, 1 = PIP)
  - Benefit-package definitions (health/dental/vision/401k/wellness/equity)

Realistic data relationships:
  - Employees with manager chains that resolve correctly through 4-5 levels
  - Leave balances with carryover history + blackout dates + accrual events
  - Performance reviews with 360-feedback shapes + goal-tracking + calibration

Persona-aware copy:
  - HR-business-partner voice (analytical, data-forward)
  - Manager voice (action-oriented, brief)
  - Employee voice (user-first, friendly)
  - Same field labelled differently per persona ("Direct Reports" / "My Team" /
    "Teammates")

Domain coverage: HR (deep), Healthcare (medium), Fintech (medium), Other
(generic fallback). Other domains add via the same per-domain JSON layout.
```

**Theme F — Accessibility audit + remediation — 2-3 weeks**

```
WCAG AA verification per token bundle:
  - Color contrast ratios for all foreground/background pairs in each register
  - Focus-visible rings have 3:1 contrast against adjacent surfaces
  - Status colors (success/warning/error) distinguishable for protanopia/deuteranopia

ARIA labels + semantics on every interactive element:
  - Button: aria-label when no visible text (icon buttons)
  - Form fields: associated <label>, aria-describedby for help text + errors
  - DataGrid: row aria-rowindex, column aria-colindex, sort state announced
  - Tabs: aria-selected, role="tab"/"tabpanel", arrow-key navigation
  - Modal: aria-modal, focus trap, focus restore on close
  - Chart: aria-label + tabular fallback table for screen readers

Screen-reader announcements for dynamic content:
  - Form validation errors announced live
  - Toast/Alert appearance announced
  - Loading state changes announced
  - DataGrid row-count changes after filter announced

Keyboard navigation:
  - All interactive elements reachable via Tab
  - Logical Tab order (DOM order = visual order)
  - Esc closes modals/popovers/menus
  - Arrow keys for menu/listbox/tab navigation
  - Enter/Space activate buttons + links

Test infrastructure:
  - axe-core integration in apps/visual-regression
  - Per-component a11y test suite
  - PR check fails on new violations
```

**Theme G — Responsive design — 3 weeks**

Today: desktop-only (1280×800 baseline). Real apps need:

```
Breakpoints in token bundles:
  mobile:  < 640px
  tablet:  640-1024px
  desktop: > 1024px

Each register's bundle gains breakpoint-aware density:
  workday: { density: { mobile: spacious, tablet: comfortable, desktop: compact } }
  (mobile rendering is more spacious because thumb targets need 44px+ tap area)

Mobile-specific component variants for high-traffic patterns:
  - AppShell.mobile: bottom-nav for primary actions + slide-up sheet for secondary
  - DataGrid.mobile: card-list layout instead of table, with swipe-actions
  - Form.mobile: full-screen step-by-step instead of multi-section scroll
  - InspectorPanel.mobile: full-screen modal instead of slide-out

Mobile-first schema patterns:
  - FilterBar.mobile: pill-list at top, "Filters" button opens bottom sheet
  - CommandPalette.mobile: full-screen search instead of centred dialog

Render-scaffold updates:
  - Capture screenshots at all 3 breakpoints
  - Vision evaluator scores all 3 viewport sizes
  - Fidelity log carries per-viewport scores
```

**Theme H — Performance — 2 weeks**

```
Component-level:
  - DataGrid virtualisation for >100 rows (using @tanstack/react-virtual)
  - Lazy-load Chart, OrgChart, CommandPalette (heavy + infrequent)
  - Skeleton states match real content layout (not generic boxes)

App-level (in render-scaffold + generated apps):
  - Code-splitting per route
  - Prefetch on link hover (Next.js default + tuning)
  - Image optimisation for all <img> in PersonCard, EmptyStateRich, etc.

Bundle size monitoring:
  - bundle-analyzer report per build
  - PR comment with bundle delta
  - Hard-fail when bundle grows >5% without justification
```

**Theme I — Custom iconography + illustrations — 1-2 weeks**

```
Icon set:
  - Replace generic Lucide with branded set (custom SVG + Lucide overrides)
  - Per-register icon style: Workday = filled solid; Linear = stroke 1.5;
    Notion = stroke 2 with rounded caps; Stripe = duotone; Figma = rounded fill

Illustrations:
  - Empty-state illustrations per domain
    (HR: empty calendar; fintech: empty ledger; etc.)
  - Onboarding artwork for first-render screens
  - 404/500 illustrations branded per register

Source: paid library (Storyset / unDraw / Streamline) or commission.
$200-2000 budget depending on scope. Out-of-scope for code-only effort.
```

**Theme J — Telemetry-driven iteration loop — ongoing**

```
Production fidelity-log feeds:
  - Daily aggregation of which patterns score lowest
  - Auto-bucketed into "missing component" / "wrong register" / "bad copy"
    via classifier on the critique JSON

Patch-agent prompt evolution:
  - Weekly review of which patches fail most
  - Refine the patch-agent system prompt based on patterns
  - Track patch-acceptance-rate over time (target: stay >80%)

Reference bank growth:
  - Auto-promotion (Wave 5 Task 7) feeds candidates from production
  - Weekly human review queue + promote/reject UI
  - Bank version-bumps when seeder prompts evolve
```

### Tier 3 success criteria

- WCAG AA passing on 100% of new components, ≥ 95% of existing components
- Mobile screenshot fidelity ≥ 7.5 (vs. desktop baseline of ≥ 8.0)
- DataGrid renders 1000-row datasets in < 200ms
- Median bundle size per generated app stays ≤ 500KB compressed
- Patch-acceptance-rate stays ≥ 80% as the system grows
- Reference bank grows organically — at least 50% of bank entries by Q3 are
  auto-promoted from real production scoring (vs. seed-script generated)

### Tier 3 implementation waves

```
Tier 3 Wave 1 — Domain data libraries (HR deep)                                    (~10 tasks)
Tier 3 Wave 2 — Accessibility audit + remediation                                  (~12 tasks)
Tier 3 Wave 3 — Responsive design (mobile-first)                                   (~12 tasks)
Tier 3 Wave 4 — Performance (virtualisation, code split, lazy-load)                (~8 tasks)
Tier 3 Wave 5 — Iconography + illustrations (mostly design work, not code-heavy)   (~6 tasks)
Tier 3 Wave 6 — Telemetry iteration loop                                           (~8 tasks)

Total: ~56 tasks, ~3-6 months (1 engineer) or ~6-10 weeks (2-3 engineers parallel)
```

## Cross-tier ongoing work

These thread through every wave:

- **Visual regression suite kept current** — every new component gets baselines on day-of
- **Schema migration corpus grows** — every notable real generation captured for safety
- **Reference bank version-bumping** — when seeder prompts change, bump version, re-seed worst cells first
- **Documentation per phase** — `docs/components/<name>.md`, `docs/registers.md`, `docs/a11y.md`, `docs/responsive.md`

## Dependencies

**Tier 2 depends on:**
- Tier 1 shipped ✅
- Reference bank seeded for at least one register (Workday) ✅ (code ready, operational seeding pending)
- Visual regression suite operational ✅
- CVA template established ✅

**Tier 3 depends on:**
- Tier 2 components in place — accessibility/responsive/performance audits need the components to exist
- Real production usage data for Wave 6 telemetry tasks — needs at least 50 generated projects
- Iconography work depends on design budget approval (or licensed asset library)

**External dependencies that block work:**
- Recharts (or Chart lib of choice) — needs npm install + bundle-size verification
- @tanstack/react-virtual — for DataGrid virtualisation
- axe-core — for a11y testing
- Playwright already in place ✅

## Out of scope (explicit)

**Not in Tier 2 or Tier 3:**

- **Multi-tenancy / RBAC primitives.** Generated apps are single-tenant. Adding role-based access control is a separate platform concern.
- **Internationalisation (i18n).** All copy is English; i18n is a Tier 4 conversation.
- **Enterprise SSO / OIDC integrations.** Auth is local NextAuth. Enterprise auth integration is a deployment concern.
- **Analytics / event tracking.** No client-side analytics shipped — privacy-first by default. Customer apps add their own.
- **Custom domain registers.** Tier 2/3 cover HR/Healthcare/Fintech/Devtools/Content/Design — the 5 registers in Tier 1. New registers (e.g. "legal", "manufacturing") are follow-up work.
- **Test data generation tooling for end-users.** Faker-driven fixtures exist; "let users author their own seed data" is platform work, not design work.

## Sequencing recommendation

**Realistic 6-month roadmap (one engineer):**

```
Month 1-2: Tier 2 Waves 1-3 (component batches)
Month 3:   Tier 2 Wave 4 (layout primitives) + Wave 6 (schema patterns + re-seed)
Month 4:   Tier 2 Wave 5 (engine richness) + Tier 3 Wave 1 (domain data)
Month 5:   Tier 3 Wave 2 (a11y) + Wave 3 (responsive) — these can interleave
Month 6:   Tier 3 Wave 4 (performance) + Wave 5 (iconography) + Wave 6 setup
```

**Two-engineer parallel: ~3 months total.**

**MVP 6-week sub-roadmap (if the ask is "make 1-2 demos truly Workday-grade"):**

```
Weeks 1-2: Tier 2 Wave 1 (Chart + DataGrid + Sparkline + Timeline)
Week 3:    Tier 2 Wave 2 partial (ApprovalStepper + PersonCard)
Week 4:    Tier 2 Wave 4 (AppShell + InspectorPanel)
Week 5:    Tier 2 Wave 6 (schema patterns + re-seed Workday register)
Week 6:    Tier 3 Wave 1 partial (HR domain data libraries)
```

After 6 weeks: a generated leave-management app would have a real DataGrid with frozen columns + sortable + status-pill cells, an accrual Chart, an approval Timeline, an InspectorPanel for employee detail drill-in, and HR-realistic data populating it. That's a Workday-grade demo for one domain.

## What this spec does NOT prescribe

- **Exact Recharts vs. Visx vs. roll-our-own** for Chart — that's a Tier 2 Wave 1 implementation decision.
- **Exact accessibility test framework** (axe-core vs. Pa11y vs. manual) — Wave 2 implementation decision.
- **Exact mobile breakpoints** in the responsive system — Tier 3 Wave 3 will tune based on real devices.
- **Iconography licensing decisions** — per-team budget call.

These are the right level of decision-deferral: the spec captures the design intent; implementation plans pick the mechanics.
