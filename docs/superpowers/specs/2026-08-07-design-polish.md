# Design Polish — Third Workstream

**Status**: spec'd, not implemented.
**Owner**: design-quality workstream.
**Companions**:
- `2026-08-07-brief-canonical.md` (Spec A — visual fidelity)
- `2026-08-07-domain-form-intelligence.md` (Spec B — form UX)

Covers the ~30-40% gap between "A + B shipped" and "professional
modern UX." Ships **after** A + B.

**Core principle** (correction from v1 of this spec): no hardcoded
per-domain archetype recipes. Discovery already produces deep domain
knowledge; planner is the aggregator. Every domain-shaped decision is
LLM-authored as structured plan output and rendered by deterministic
passes that validate against real registries. Same pattern as
`resource-registry`, `nav-flow`, `plan schema`, `submit-authority`,
etc. Recipes-per-domain don't scale beyond a small enumerated list;
LLM-authored intent scales to N.

---

## Problem

Even after A (correct visual identity) + B (form intelligence) ship,
generated apps will still feel *unfinished*:

- **Dashboards are generic** — no domain-shaped KPI tiles, no activity
  streams, no relevant heatmaps/timelines. Every dashboard looks the
  same 4-card grid.
- **Signature moves in the brief are unrendered** — brief authors them,
  nothing consumes.
- **Content voice is generic-CRUD** — empty states say "No items yet",
  error toasts say "Something went wrong". Brief captures
  `identity.voice`; nothing uses it.
- **No motion system** — no coordinated transitions, hover states, or
  micro-interactions.
- **Edge-case pages are template stubs** — 404 / 403 / 500 / loading.
- **Interaction depth is thin** — no keyboard shortcuts, no command
  palette, no bulk actions, no saved views.
- **Component variety is narrow** — library has 100+ components but
  planner reaches for the same 20.
- **Dark mode is spotty** — brief supports it; many primitives hardcode
  light-mode colors.
- **True responsive is aspirational** — desktop-first + mobile Expo
  scaffolding exist, but tablet/mobile-specific layouts per screen
  aren't authored.

Discovery already produces rich per-domain output (patterns, pitfalls,
palette recommendations). The gap is that the pipeline downstream
doesn't have structured hooks to consume it — so the LLM's domain
knowledge evaporates between discovery and generation.

## Solution

Nine slices. Each one either:
1. **Extends the plan/discovery/brief schema** so the LLM can emit
   structured intent for a domain-shaped decision, and
2. **Adds a deterministic pass** that validates the intent against
   real registries (component, entity, workflow) and applies it.

No new LLM calls in generation. No per-domain Python recipes.

## Non-goals

- No changes to visual tokens (Spec A).
- No changes to form primitives (Spec B).
- No new LLM in the Figma design chain (Spec A's non-negotiable).
- No hardcoded archetype behavior. Slice names may reference archetypes
  (`archetype: kanban_board`) but only as *content the LLM emits into
  the plan*, not as Python files we enumerate.

## Design

Nine slices, dependency-ordered:

### Slice 1 — Dashboard composition intent (~2 days)

**Problem**: dashboards are the app's front door and every one is a
4-card grid.

**Fix — the LLM emits structured composition; renderer applies it**:

- Extend discovery/planner output with a `dashboard_composition` block:

  ```json
  {
    "dashboard_composition": {
      "tiles": [
        {"kind": "stat", "label": "Total Units", "calc": "count", "entity": "unit"},
        {"kind": "stat", "label": "Occupancy %", "calc": "ratio", "numerator": "unit.status=occupied", "denominator": "unit"},
        {"kind": "stat", "label": "Rent Collected MTD", "calc": "sum", "entity": "rent_payment", "field": "amount", "filter": "paid_date>=month_start"},
        {"kind": "stat", "label": "Overdue", "calc": "count", "entity": "rent_payment", "filter": "status=overdue"}
      ],
      "widgets": [
        {"component": "Heatmap", "title": "Occupancy by Property", "bindsTo": "unit", "groupBy": "property_id", "colorBy": "status"},
        {"component": "Kanban", "title": "Maintenance", "bindsTo": "maintenance_ticket", "groupBy": "status"},
        {"component": "Table", "title": "Recent Payments", "bindsTo": "rent_payment", "sort": "paid_date desc", "limit": 5}
      ],
      "layout": "kpi_row_over_two_column_widgets"
    }
  }
  ```

- Planner prompt guidance: "Compose dashboards by reasoning from the
  domain. You have access to <full component registry>, <full entity
  registry>, <known calc kinds: count|sum|ratio|avg|min|max|distinct>.
  Pick tiles that answer the most-important question a user of this
  app opens the dashboard to see."
- Deterministic renderer `services/dashboard_composer.py` (~200 lines):
  - Validates every `component` is in the registry.
  - Validates every `entity`, `field`, `filter` clause resolves against
    the resource registry.
  - Validates every `calc` is a known formula.
  - Compiles to dashboard page schema.
  - Repair pass: unresolvable references get a `[missing]` marker
    logged + a fallback widget swapped in (never silently dropped).

**Files**:
- `backend/schemas/plan.py` — `dashboard_composition` field (~30 lines)
- `backend/services/dashboard_composer.py` (~250 lines)
- `backend/services/plan_validator.py` — new rule (~30 lines)
- `backend/agents/planner.py` — prompt update (~80 lines)
- `backend/tests/services/test_dashboard_composer.py` (~250 lines)

~640 lines, ~2 days.

### Slice 2 — Signature-move rendering (~2 days)

**Problem**: brief authors `signature_moves`, nothing consumes them.

**Fix — brief-author picks from a registered vocabulary; renderer
applies**:

- Small registry of move kinds `services/signature_moves/`:
  - Each move is `{kind, applicability, renderer}` where `applicability`
    is a schema-node predicate (e.g. `Table bound to entity with status
    enum`) and `renderer` is a pure `(node, brief) -> node` mutation.
  - Anchors updated so authored moves use only registered kinds.
  - Brief-author prompt is aware of the registry — same as planner is
    aware of the component registry — and picks from it.
- Post-gen pass `apply_signature_moves.py` iterates brief moves,
  finds applicable nodes, applies renderers. Ignores unknown kinds
  (logged, never crashes).
- Adding a new move = one file with a predicate + a renderer. No spec
  change, no schema change. Scales to N without enumeration.

**Files**:
- `backend/services/signature_moves/__init__.py` — registry
- `backend/services/signature_moves/{ledger_row,keyline_breadcrumb,timeline_row,velocity_sparkline,status_stripe,...}.py`
  (~60 lines each × ~15 initial = ~900 lines; grows organically)
- `backend/services/apply_signature_moves.py` (~200 lines)
- `backend/services/design_brief_author.py` — inject registered-moves
  vocabulary into prompt (~40 lines)
- `packages/library/src/components/Table/variants/ledger.tsx` (new variant)
- `backend/tests/services/test_apply_signature_moves.py` (~200 lines)

~1400 lines, ~2 days. Move count grows organically; not a fixed set.

### Slice 3 — Content voice bank (~2 days)

**Problem**: empty states + toasts + notification templates use
generic-CRUD copy. Brief captures voice; nothing reads it.

**Fix — LLM authors a content bank once, deterministic passes read from it**:

- Extend brief with a `content_bank` field, authored at brief-author
  time (one Anthropic call, same as brief itself). Populated using
  brief.identity.voice + register + domain:

  ```json
  {
    "content_bank": {
      "empty_states": {
        "list": "No {entity_plural} on file yet",
        "search": "No {entity_plural} match \"{query}\"",
        "filtered": "No {entity_plural} match your filters",
        "first_use": "Add your first {entity_singular} to get started"
      },
      "toasts": {
        "created": "{entity_singular} recorded",
        "updated": "Changes saved to {entity_singular}",
        "deleted": "{entity_singular} removed",
        "error_generic": "Couldn't save — try again",
        "error_permission": "You don't have permission to do that"
      },
      "notifications": {
        "task_assigned": "You've been assigned a {task_kind}",
        "approval_needed": "A {entity_singular} needs your approval",
        ...
      },
      "cta_verbs": {
        "primary": "Record",
        "create": "Add",
        "delete": "Remove"
      }
    }
  }
  ```

- Brief-author gains a new subsection in its prompt: "Given the app's
  voice + register + domain, populate the content bank."
- Deterministic passes read the bank: `deterministic_strings.py`
  (empty states, list captions) + `form_scaffold.py` (submit button
  labels) + `notification_templates.py` (subject/body).
- Substitution is templated ({entity_singular}, {entity_plural},
  {query}, {task_kind}) using per-entity display-name from the
  resource registry.

**Files**:
- `backend/schemas/design_brief.py` — `ContentBank` model (~50 lines)
- `backend/services/design_brief_author.py` — extended prompt (~80 lines)
- `backend/services/content_bank_reader.py` (~200 lines)
- `backend/services/deterministic_strings.py` — voice-aware branch (~100 lines)
- `backend/services/form_scaffold.py` — CTA labels from bank (~40 lines)
- `backend/services/notification_templates.py` (new, ~150 lines)
- `backend/tests/services/test_content_bank.py` (~250 lines)

~870 lines, ~2 days. Voice count = infinite (LLM-authored); no per-voice files.

### Slice 4 — Motion tokens + primitive refresh (~2 days)

**Problem**: no page transitions, no coherent hover states, no
success-confirmation micro-interactions.

**Fix — brief authors concrete motion values; tokens carry them through**:

- Brief author populates a `motion` object with concrete values (not
  an enum bucket):

  ```json
  {
    "motion": {
      "duration_fast_ms": 120,
      "duration_medium_ms": 240,
      "duration_slow_ms": 480,
      "ease_out": "cubic-bezier(0.2, 0.0, 0.0, 1.0)",
      "ease_in_out": "cubic-bezier(0.4, 0.0, 0.2, 1.0)",
      "reduce_motion_respect": true
    }
  }
  ```

  Brief-author decides values based on identity/register (a
  formal-technical enterprise brief lands 120/240/480; a playful
  consumer brief might pick 180/320/600 with springier eases). No
  enum vocabulary — the LLM picks numbers.
- `brief_to_design_spec` copies motion values verbatim into
  `--motion-*` and `--ease-*` CSS variables.
- Library primitives get motion refresh: Button (press ripple), Card
  (elevate on hover), Table row (bg-tint), Modal (scale-in), Toast
  (slide-in-from-bottom) — all driven by tokens.
- Page transitions via Next.js App Router `<Transition>` — respects
  `prefers-reduced-motion`.

**Files**:
- `backend/schemas/design_brief.py` — `Motion` model with concrete fields (~30 lines)
- `backend/services/design_brief_author.py` — extended prompt section on motion (~30 lines)
- `backend/services/brief_to_design_spec.py` — motion tokens (~30 lines)
- `packages/library/src/components/{Button,Card,Table,Modal,Toast}/*.tsx` — motion refresh (~50 × 5 = ~250 lines)
- `backend/templates/standalone-app/src/components/PageTransition.tsx` (~80 lines)
- Library rebuild + re-vendor.

~470 lines + rebuild, ~2 days.

### Slice 5 — Edge-case pages (~1.5 days)

**Problem**: 404 / 403 / 500 / loading / permission-denied are
unstyled template stubs.

**Fix**:
- Template overhaul: `not-found.tsx`, `error.tsx`, `forbidden.tsx`,
  `loading.tsx`, `maintenance.tsx` — brief-themed, use `content_bank`
  from Slice 3 for copy, offer a helpful action link derived from
  plan (e.g. "Return to Manager Dashboard").
- Illustrations: monogram-style branded initial from
  `brief.palette.brand` + first letter of app name — simple, deterministic
  SVG. No generative art.
- Pure infrastructure — no LLM in generation.

**Files**:
- `backend/templates/standalone-app/src/app/{not-found,error,forbidden,loading,maintenance}.tsx` (~400 lines)
- `backend/services/edge_page_customizer.py` (~120 lines)
- `backend/tests/services/test_edge_pages.py` (~150 lines)

~670 lines, ~1.5 days.

### Slice 6 — Component variety through registry-aware planner (~1.5 days)

**Problem**: library has 100+ components but planner picks from the
same 20.

**Fix — planner sees the full registry; picks freely; validator rejects invalid**:

- No hardcoded "if entity-name-contains-log use ActivityStream" rules.
- Planner prompt injection: full component catalog with `{name,
  purpose, when_to_use, when_not_to_use, props, example}` from the
  library manifest (already exists as `starter.ts`).
- Planner's page-authoring prompt: "For each entity/page, pick the
  component that best fits its purpose. You have the full catalog.
  Don't default to Table unless the data really is tabular."
- Validator: every component picked must be in the registry (already
  enforced). Add a completeness metric — track how many distinct
  components each generation uses; alert if the ratio drops.

**Files**:
- `backend/services/library_manifest.py` — expose full catalog with
  purposes (~150 lines)
- `backend/agents/planner.py` — inject catalog into prompt (~60 lines)
- `backend/services/component_diversity_metric.py` (~80 lines,
  observability)
- `backend/tests/services/test_component_diversity.py` (~150 lines)

~440 lines, ~1.5 days. No per-component hint files — the LLM decides.

### Slice 7 — Interaction depth (~2 days)

**Problem**: no keyboard shortcuts, no command palette, no bulk
actions, no saved filter views, no global search.

**Fix — open feature registry, planner picks freely**:

- Feature registry `services/interaction_features/`: each feature is
  a `{slug, purpose, when_to_use, when_not_to_use, component_name}`
  entry pointing at a library component that implements it.
- Initial registry entries: `command_palette`, `bulk_actions`,
  `saved_views`, `global_search`, `keyboard_shortcuts_overlay`.
  Not a fixed list — adding a 6th (e.g. `contextual_help_overlay`) =
  one library component + one registry entry.
- Planner reads the registry the same way it reads the component
  registry, decides which features suit the app based on scale,
  complexity, and journey.
- Plan emits `features: list[str]` — validated against the registry
  (unknown slug → validator error).
- Deterministic post-gen emits the picked features into shell/header.

**Files**:
- `packages/library/src/components/{CommandPalette,BulkActionBar,SavedViewsPicker,GlobalSearch,KeyboardShortcuts}/*.tsx` (~200 × 5 = ~1000 lines)
- `backend/services/interaction_features/__init__.py` — registry (~120 lines)
- `backend/services/interaction_features_emitter.py` — post-gen wiring (~150 lines)
- `backend/services/plan_validator.py` — features rule (~20 lines)
- `backend/agents/planner.py` — registry-aware prompt (~50 lines)
- Library rebuild + re-vendor.

~1340 lines, ~2 days. No hardcoded 4-feature list — an open registry
grown one entry at a time.

### Slice 8 — Dark mode + responsive audit (~2 days)

**Problem**: brief supports dark mode; primitives hardcode light. No
tablet-specific layouts.

**Fix**:
- Dark-mode sweep of every library component: replace hardcoded colors
  with `var(--color-*)` tokens. Add `@media (prefers-color-scheme: dark)`
  + `[data-theme="dark"]` branches.
- `ThemeToggle` component in library.
- Brief exposes `responsive: {primary_form_factor, breakpoints_priority}`
  with concrete values authored by brief-author from discovery
  signals — not an enum bucket. Discovery already surfaces whether
  the app is for field workers (property inspector, logistics, food
  delivery) vs office workers (CRM, finance) vs mixed. Brief-author
  reads `identity` + `patterns` and emits concrete responsive intent:

  ```json
  {
    "responsive": {
      "primary_form_factor": "mobile" | "desktop" | "tablet",
      "breakpoints_priority": ["mobile", "tablet", "desktop"],
      "layout_variants": ["bottom_tabs", "sidebar_collapse", "sidebar_persistent"]
    }
  }
  ```

  `layout_variants` is an open list drawn from a shell-templates
  registry (same shape as feature registry).
- Deterministic shell composers respect the brief field; unknown
  layout variants get validated + rejected before they reach code.

**Files**:
- `packages/library/src/components/**/*.tsx` — dark-mode sweep (~40 files × 20 lines = ~800 lines)
- `packages/library/src/components/ThemeToggle/*.tsx` (new, ~80 lines)
- `backend/services/shell_templates.py` — responsive_priority branches (~120 lines)
- `backend/schemas/design_brief.py` — `responsive_priority` field (~15 lines)

~1000 lines, ~2 days.

### Slice 9 — Brand assets (illustrations + logo) — may defer (~2 days)

**Problem**: no logo generation, no empty-state illustrations, no
onboarding hero art.

**Fix**:
- Logo: `services/logo_generator.py` emits a deterministic monogram
  SVG (letter in brand color, geometric container from
  `brief.layout.radius`).
- Empty-state illustrations: `IllustratedEmpty` component with 10
  SVGs shipped in library; colors adopt from tokens; illustration
  `kind` picked by planner/scaffolder based on context.
- Onboarding hero: dashboard first-run state uses a themed block with
  app name + brief tagline + "Get started" CTA.

**Files**:
- `backend/services/logo_generator.py` (~250 lines)
- `packages/library/src/components/IllustratedEmpty/{index.tsx,illustrations/*.svg}` (~500 lines)
- Library rebuild + re-vendor.

~750 lines, ~2 days. Consider ship-later.

## Rollout

Each slice ships behind `FORGE_POLISH_*` flag, default off.

**Recommended order (highest impact → lowest):**
1. Slice 1 (dashboard composition) — biggest visual difference per unit of work.
2. Slice 2 (signature moves) — pays off the brief investment.
3. Slice 3 (content bank) — voice consistency across the app.
4. Slice 6 (component variety) — cheap, reaches into unused library.
5. Slice 4 (motion) — polish that reads as care.
6. Slice 5 (edge pages) — small but visible during errors.
7. Slice 8 (dark mode + responsive) — cross-cutting cleanup.
8. Slice 7 (interaction depth) — biggest per-slice, feature-flagged.
9. Slice 9 (brand assets) — optional, may defer.

Slices 1, 2, 3, 6 are largely independent and parallelizable.

**Total scope**: ~17-19 engineering days linear / ~10-12 with
parallelism.

## Testing

- Per-slice: standard unit + integration + snapshot.
- **Cross-slice acceptance corpus**: 4 novel domain apps (property
  mgmt, healthcare scheduling, HR onboarding, retail POS) regenerated
  after each slice. Human eyeball comparison against reference apps
  in each domain. **Novel = not on any hardcoded list.**
- **Dashboard composition validator**: for each corpus app, verify
  planner-emitted `dashboard_composition` resolves cleanly against the
  registry (no `[missing]` markers).
- **Voice bank round-trip**: brief-author for each corpus produces a
  content bank that varies meaningfully — no two apps ship the same
  empty-state copy verbatim.

## Rollback

Each slice's flag flips independently. Slices 1, 2, 3, 6 are post-gen
passes — flag off = pass doesn't run = existing generation unchanged.
Slices 4, 8, 9 touch library dist — rebuild without the change to
revert.

## Risks

- **Planner over-emission** (Slice 1): planner might invent widget
  kinds not in the registry. Validator rejects, repair pass swaps in
  fallback — never silently drop. Observability metric tracks
  rejection rate; if high, prompt needs tightening.
- **Signature-move applicability drift** (Slice 2): a move's
  applicability predicate is a Python function; the anchor detail
  string describes the *what*, the predicate implements the *when*.
  They can drift. Mitigation: predicates unit-tested against synthetic
  schemas; anchor detail strings link to registered kinds by name.
- **Voice bank blandness** (Slice 3): LLM might produce boring bank
  entries for a "formal_technical" voice. Mitigation: brief-author
  prompt shows a few contrasting examples across voice tones.
- **Motion accessibility** (Slice 4): all motion respects
  `prefers-reduced-motion`; exhaustive audit needed.
- **Feature bloat** (Slice 7): Cmd-K + bulk + saved views + search on
  every app is overkill for small tools. Planner emits
  `brief.features` based on app scale.
- **Library dist proliferation**: multiple slices rebuild the library.
  Batch into weekly releases to avoid vendoring churn.

## The professional-modern threshold

After A + B + C ship in that order, generated apps will:

- Match Figma sources byte-for-byte (A)
- Have real form intelligence (B)
- Compose domain-shaped dashboards from planner intent (C1)
- Render brief signature moves as actual visual behavior (C2)
- Speak in the app's voice via content bank (C3)
- Reach into the full component library, not just defaults (C6)
- Feel considered in motion (C4)
- Handle edges gracefully (C5)
- Work in dark mode + across breakpoints (C8)
- Support power users via features when scaled up (C7)
- Optionally have brand marks + empty-state art (C9)

**Everything here is LLM-authored intent + deterministic render.** No
per-domain enumeration. New domains work automatically because
discovery + planner already handle them; the deterministic passes just
respect what those authors emit.

A + B alone: ~60-70%. A + B + C1-3: ~80%. All three fully shipped:
~95%. Last 5%: per-app hand craft that a human designer would add.
