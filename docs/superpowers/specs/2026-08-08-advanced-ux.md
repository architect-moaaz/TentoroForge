# Advanced UX — Fifth Workstream

**Status**: spec'd, not implemented.
**Owner**: design-quality workstream.
**Companions**:
- `2026-08-07-brief-canonical.md` (Spec A — visual fidelity)
- `2026-08-07-domain-form-intelligence.md` (Spec B — form UX)
- `2026-08-07-design-polish.md` (Spec C — dashboards/voice/motion)
- `2026-08-07-domain-intelligence-cleanup.md` (Spec D — bypass cleanup)

Covers the remaining "professional modern UX" gap that A/B/C/D leave
unaddressed:
- **Advanced interactions**: drag/drop, real-time presence, optimistic
  UI, contextual menus, undo/redo across the app
- **Complex accessibility**: focus management, ARIA live regions,
  screen-reader announcements, WCAG 2.2 AA CI gate
- **Advanced UX patterns**: multi-step wizards, inline table editing,
  master-detail split view, rich text with mentions, file upload with
  progress+retry, auto-save with conflict resolution, filter query
  builder, onboarding tours

Ships **after** A+B+C+D and follows the same discipline: LLM-authored
intent + deterministic renderer + real registry validation. No new
Python catalogs.

---

## Problem

After A/B/C/D ship, generated apps are visually correct, forms are
intelligent, dashboards are domain-shaped, and the codebase is clean.
But three product-quality thresholds remain:

**Interaction depth is table-stakes for enterprise apps**. Every
serious tool has drag-to-reorder, bulk-select-with-action, optimistic
UI, and undo — Trello, Linear, Notion, Airtable. Generated Forge apps
don't. C7 covers Cmd-K + bulk actions + saved views + global search;
this spec picks up where C7 stops.

**Accessibility is a compliance and quality gate we don't pass**.
Generated apps have accidental accessibility (semantic HTML from
library primitives) but no deliberate accessibility (focus management,
ARIA live regions, screen-reader announcements, WCAG contrast audit).
A generated app is not something a compliance-sensitive customer
(healthcare, government, education) can ship as-is.

**Advanced UX patterns unlock domains that don't fit CRUD**. Multi-step
wizards (loan applications, patient intake), inline editing (finance
spreadsheets), master-detail (email clients), rich-text with mentions
(collaboration tools), auto-save with conflict resolution (docs) —
these are the patterns that turn "runs and saves data" into "feels
like the product I'd buy."

## Solution

Three waves, roughly equal size, largely independent:
- **Wave 1**: Advanced interactions (drag/drop, presence, optimistic UI, undo, contextual menus)
- **Wave 2**: Accessibility spine (focus management, live regions, WCAG CI gate)
- **Wave 3**: Advanced UX patterns (wizards, inline edit, master-detail, rich text, auto-save, filter DSL, tours)

Each wave follows the platform's spine: LLM authors intent in the
plan/brief, deterministic passes validate + render.

## Non-goals

- **No changes to A/B/C/D scope.** This spec is additive.
- **No custom illustrations or hand-crafted brand moments** (Spec C
  Slice 9 covers what's automatable; the rest is human designer work).
- **No AI-assisted authoring inside the generated app** (agents inside
  the generated app for the end-user — separate initiative).
- **No CRDT-based real-time collaboration** — presence + optimistic
  concurrency only. Full multiplayer editing is out of scope.

## Design

Three waves, largely independent (any order):

### Wave 1 — Advanced interactions (~5-6 days)

**Delivers**: drag-to-reorder, drag-to-different-lane (kanban), bulk
select+action, contextual right-click menus, undo/redo across the app,
optimistic UI with rollback, real-time presence indicators.

**Approach — planner declares intent, library primitives implement**:

- Planner emits per-list/kanban `interactions: {reorderable, movable_between_lanes?, bulk_actions?}` — a small structured intent block.
- Library gains new components/variants:
  - `Table` — `reorderable?: boolean` prop wires up drag handles + `PATCH /:entity/reorder` endpoint (deterministic pass emits the endpoint if `reorderable` set).
  - `Kanban` — `moveBetweenLanes?: {sourceField}` wires drag-across-column + `PATCH /:entity/:id/:field` on drop.
  - `ContextMenu` — new library primitive, planner emits per-row context actions from workflow catalog.
  - `UndoManager` — global toast bar with "Undo" button, listens to workflow dispatches.
  - `PresenceIndicator` — WebSocket-lite (SSE-based) presence stream; shows avatars of other users on the same page.
  - `OptimisticProvider` — form/action wrapper that renders the intended state immediately and rolls back on error.

- **Runtime**: extends `@forge/renderer` with a `MutationQueue` that
  wraps every workflow dispatch: optimistic apply → server confirm →
  toast + rollback on error. Undo works by inverting the mutation.

- **Server-side**:
  - `/api/data/:entity/reorder` — takes `{ids: [], newOrder: []}`, updates a `sortOrder` column
  - `/api/presence/:route` — SSE stream of `{userId, cursor?, focusedField?}` events
  - `sortOrder` column auto-added by post-gen fix when planner declares `reorderable`

**Files**:
- Backend: `services/interaction_authority.py` (~200 lines) — validates planner-emitted interaction intent against registry
- Backend: `services/reorder_column_pass.py` (~120 lines) — post-gen adds `sortOrder` col + endpoint when needed
- Backend: `services/presence_endpoint.py` (~150 lines) — SSE stream implementation
- Backend template: `/api/presence/route.ts` (~100 lines)
- Runtime: `packages/renderer/src/mutation-queue.ts` (~250 lines)
- Runtime: `packages/renderer/src/undo-manager.ts` (~180 lines)
- Runtime: `packages/renderer/src/presence-client.ts` (~120 lines)
- Library: `Table.reorderable`, `Kanban.moveBetweenLanes`, new `ContextMenu`, `PresenceIndicator`, `UndoManager` (~600 lines)
- Planner: prompt hardening + plan schema fields (~80 lines)
- Tests: (~600 lines)

Net: ~2400 lines, ~5-6 days.

### Wave 2 — Accessibility spine (~4-5 days)

**Delivers**: focus management, ARIA live regions, screen-reader
announcements for async operations, keyboard navigation enforcement,
WCAG 2.2 AA CI gate, high-contrast mode support, reduced-motion
respect end-to-end.

**Approach — accessibility becomes an infrastructure primitive, not
per-component vigilance**:

- **Focus primitives** in `@forge/library`:
  - `FocusTrap` — used by every Modal/Drawer/Popover; auto-restores focus on close
  - `SkipLink` — auto-injected into the shell; skips to `<main>`
  - `FocusRing` — universal focus-visible style using tokens (respects `--focus-ring-color` from brief)
  - `AutoFocus` — declarative first-focusable-on-mount for forms/dialogs

- **ARIA live-region service**:
  - `LiveRegion` singleton renders a `<div aria-live="polite">` and `<div aria-live="assertive">` under root
  - `announce(text, urgency)` utility — every workflow dispatch calls it on success/error
  - Toast component wires to live region automatically

- **Screen-reader announcements**:
  - Every async mutation announces success/failure
  - Table sort direction changes announced
  - Filter application announces result count
  - Route navigation announces new page title

- **Keyboard navigation enforcement**:
  - Every interactive component reachable via keyboard (Tab, Shift+Tab, Arrow keys where appropriate)
  - Automated test suite: Puppeteer script tabs through every page, asserts no dead ends
  - Modal/Popover Escape-to-close enforced

- **WCAG CI gate**:
  - `axe-core` audit runs on every generated page during verify pass
  - Contrast ratio checked against brief tokens (Spec A brief carries fg/bg pairs; validator ensures 4.5:1 minimum for AA)
  - Report in `verify-run/accessibility.json`; fails the verify gate if violations exceed threshold

- **High-contrast + reduced-motion**:
  - Brief already exposes `motion` (Spec C Wave 4); this wave adds `high_contrast_variant` (deterministic transformation of the palette)
  - `[data-theme="high-contrast"]` root attribute; ThemeToggle offers it
  - Every animation respects `prefers-reduced-motion` (audited in axe pass)

- **Font-size scaling**:
  - Enforce `rem`-based sizing everywhere (audit library); no hardcoded `px` for text
  - App remains functional at 200% zoom (axe-core has a check for this)

**Files**:
- Library: `FocusTrap`, `SkipLink`, `FocusRing`, `AutoFocus`, `LiveRegion` primitives (~500 lines)
- Runtime: `packages/renderer/src/announce.ts` (~120 lines), auto-wired to workflow dispatches
- Backend: `services/accessibility_audit.py` (~250 lines) — post-gen axe-core runner + report
- Backend: `services/high_contrast_pass.py` (~150 lines) — token derivation for high-contrast variant
- Backend: `services/self_verify_pass.py` — new accessibility gate (~80 lines)
- Library sweep: audit ~40 components for hardcoded `px` sizes and missing ARIA (~400 lines edits)
- Playwright script: `scripts/keyboard_nav_audit.ts` (~200 lines)
- Tests: (~500 lines)

Net: ~2200 lines, ~4-5 days.

### Wave 3 — Advanced UX patterns (~6-7 days)

**Delivers**: multi-step wizards, inline table editing (Airtable-style
data grid), master-detail split view, rich text with mentions/embeds,
file upload with progress+retry, auto-save with conflict resolution,
filter query builder, onboarding tours.

**Approach — same as everything else: planner declares intent per
page, deterministic pass emits schema, library implements**:

- **Multi-step wizards**:
  - Plan schema: `page.wizard: {steps: [{id, title, fields[], nextIf?}]}` — planner emits when a workflow is multi-input or approval-branching
  - Library: `Wizard` component with step progression, back/next validation, review-before-submit
  - Deterministic post-gen: workflow trigger inputs collapse into wizard when planner declares steps

- **Inline table editing (data grid)**:
  - Plan schema: `page.list.editable_columns: [col_name]`
  - Library: `Table.editable` mode — cells become inputs on click, save on blur/Enter, revert on Escape
  - Row-level dirty state + save-all toolbar

- **Master-detail split view**:
  - Plan schema: `page.layout: "master_detail" | ...` with `detail_route` field
  - Library: `SplitView` component — list on left, selected detail on right, URL syncs to `/:base/:selectedId`
  - Keyboard-nav between list items updates detail without page reload

- **Rich text with mentions**:
  - Library: `RichTextEditor` (already exists) gains `mentions: {sources: [entity]}` prop
  - `@` triggers autocomplete over the declared entity source
  - Mentions serialize to `@[Entity:id]` markup; renderer resolves back to user name + link

- **File upload with progress+retry**:
  - Library: `FileUpload` (already exists) gains progress bar + retry on failure
  - Runtime: chunked upload via presigned S3/local URLs

- **Auto-save with conflict resolution**:
  - Long-form pages (rich text, detail edit) auto-save every N seconds
  - Server returns `version` with each save; conflict → show diff + user-picks-side dialog

- **Filter query builder**:
  - Plan schema: `page.list.filters: [{field, operators}]` — planner emits per list page
  - Library: `FilterBuilder` component — chip-based expression builder ("Status IS Active AND Amount > 100")
  - Runtime: compiles to SQL-safe query params on the API

- **Onboarding tours**:
  - Brief already carries `content_bank` (Spec C Wave 3); extend with `tours: [{route, steps: [{selector, title, body}]}]` — LLM-authored per app
  - Library: `TourOverlay` component — spotlighted highlights + step-by-step popovers
  - Auto-triggers on first-time user (`localStorage` gate)

**Files**:
- Backend: `schemas/plan.py` — new per-page fields (~150 lines)
- Backend: `services/wizard_pass.py` (~200 lines)
- Backend: `services/split_view_pass.py` (~180 lines)
- Backend: `services/filter_builder_pass.py` (~150 lines)
- Backend: `services/tour_pass.py` (~120 lines)
- Backend: `services/plan_validator.py` — new rules (~80 lines)
- Backend: `agents/planner.py` — prompt (~80 lines)
- Library: `Wizard`, `SplitView`, `FilterBuilder`, `TourOverlay`, `Table.editable`, `RichTextEditor.mentions`, `FileUpload.progress`, `AutoSaveManager` (~1400 lines)
- Runtime: chunked upload + auto-save engine (~350 lines)
- Tests: (~700 lines)

Net: ~3400 lines, ~6-7 days.

## Rollout

Each wave ships behind `FORGE_UX_*` flag, default off. Waves are
independent — any order.

**Recommended order (highest impact first)**:
1. **Wave 2** (accessibility) — largest correctness win + unblocks
   compliance-sensitive customers immediately. Ship first.
2. **Wave 1** (advanced interactions) — biggest visible polish
   difference; every generated app feels more capable.
3. **Wave 3** (advanced UX patterns) — biggest per-slice; feature-flagged
   per pattern so partial adoption is fine.

**Sequencing with A/B/C/D**:
- Wave 2 (accessibility) can ship WITHOUT A/B/C/D — it's cross-cutting
  and standalone. Ship independently if that's higher priority.
- Wave 1 + Wave 3 assume Spec B (form intelligence) and Spec C (voice
  bank, motion tokens) landed — they consume those as inputs.

**Total scope**: ~15-18 engineering days linear, ~8-10 with
parallelism.

## Testing

- Per-wave: unit + integration + snapshot as usual.
- **Accessibility corpus**: fixed set of 5 apps run through axe-core
  after every wave; regression fails CI. WCAG contrast checked against
  brief tokens.
- **Keyboard navigation smoke**: Playwright script tabs through every
  page of a representative app; must reach every interactive element
  without a mouse.
- **Screen-reader smoke**: VoiceOver (macOS) + NVDA (Windows) manual
  audit for each wave; documented findings + fixes before wave ships.
- **Advanced pattern acceptance**: 4 apps demonstrating each new
  pattern (wizard for loan application, inline edit for expense
  tracker, master-detail for email client, rich-text mentions for
  team chat).

## Rollback

Each wave's flag flips independently. Wave 2 (accessibility) primitives
degrade gracefully — `FocusTrap` disabled just skips the focus trap,
which is worse UX but not broken. Waves 1/3 add net-new components
behind planner intent; disabling the flag means planner skips emitting
the intent, and no new UI appears.

## Risks

- **Accessibility CI gate blocks legitimate merges** (Wave 2): axe-core
  can be noisy. Mitigation: threshold-based (e.g. "fail on any
  critical violation, warn on serious"); tunable per project.
- **Real-time presence adds infrastructure** (Wave 1): SSE presence
  stream requires backend endpoint + Redis/in-memory session pool.
  If the ops burden is too high, defer presence to a Wave 1b.
- **Optimistic UI + workflow retries** (Wave 1): complex interaction
  when a workflow itself has retries — the client might roll back
  before the server retry succeeds. Design carefully.
- **LLM emission for wizards** (Wave 3): planner needs to correctly
  decompose a multi-input workflow into steps. If LLM emission is
  weak, apps degrade to single-page forms (safe fallback).
- **Tours require good selectors** (Wave 3): tour steps target CSS
  selectors that must remain stable across regenerations.
  Mitigation: brief emits tours against `data-tour="..."` attributes
  that library primitives already ship.

## The professional-modern threshold (revised, after all 5 specs)

After A+B+C+D+E ship:

- Visual fidelity (byte-exact for Figma, brief-driven for text) — A
- Form intelligence (labels, real pickers, currency, FK auto-fill) — B
- Dashboards + signature moves + voice + motion + edges — C
- LLM-authored intent everywhere, no domain hardcoding — D
- Drag/drop, presence, optimistic UI, undo across the app — E1
- WCAG 2.2 AA compliance-ready — E2
- Wizards, inline edit, split view, rich text, auto-save — E3

**Total scope A+B+C+D+E**: ~7-9 weeks with parallelism, ~14-16 linear.
Real multi-team initiative.

**What still isn't there** (honest, terminal state):
- Hand-crafted delight moments and unique brand micro-interactions
- Custom illustrations beyond automatable branded initials
- Live domain-authentic seed data (still "John Doe")
- Multi-tenant / enterprise features (SSO/SAML, RBAC at fine grain, audit logs)
- Full multiplayer collaboration (CRDT-based real-time editing)
- Native mobile UX beyond Expo scaffolding
- Voice/gesture-driven interfaces
- Deep integration polish for popular SaaS (Slack, Notion, Salesforce)

That's the ceiling for a generative pipeline before human designer +
customer-specific engineering takes over. A+B+C+D+E delivers "an app
you'd ship to internal users on day one" and "an app you'd ship to
paying customers after one designer-week of polish." Neither more nor
less.

## Follow-ups (potential Spec F, out of scope)

- **Enterprise readiness**: SSO/SAML, fine-grained RBAC, audit logs,
  data export, SCIM provisioning.
- **Multiplayer editing**: CRDT-based real-time collaboration (Yjs
  integration).
- **Voice interface**: speech-to-action for admin flows, mobile-first.
- **Deep integrations**: opinionated recipes for Slack notifications,
  Salesforce sync, Notion embed, Zapier hooks.
