# Planner-as-App-Designer — SP1: Archetypes, Features & Guardrail

**Date:** 2026-06-13
**Status:** Design approved, pre-implementation
**Branch:** forge-v3
**Part of:** "Option B" (planner designs the app, not just infers a database). Full
scope = Option 3 (incl. new domain-feature engine), open-with-guardrails, prompt path.
This spec is **Sub-Project 1** of that effort.

## Problem

Prompt-generated apps all look and behave alike — same colours, same layouts, same
options. The cause is structural: the generator produces a **CRUD-over-entities
admin app** with a fixed shape. The LLM fills in entity names/fields, but:

- The planner only knows **6 page types** (`page_type_classifier.classify_page`:
  list/detail/form/dashboard/auth/error) and never picks richer ones.
- The richer types that *exist* in `services/page_type.py`
  (workspace/console/inspector/wizard/audit-log/report) have **no templates** —
  they fall to a generic ad-hoc fallback.
- Domain "features" are limited to standard CRUD + (maybe) one approval workflow.
- Layout/theme also **default-collapse**: the planner emits coarse domains
  (`general/hr/saas`) that miss the Title-Case keys in `industry_design.py`, so
  almost every app gets the same `_DEFAULT_LAYOUT` and `"ocean"` theme.

The components for richer pages **already exist** (all 99 registered as schema
nodes: Kanban, Calendar, Timeline, Chart, Tree, InspectorPanel, ApprovalStepper,
ActivityFeed, DataGrid, Tabs, FilterBar…). What's missing is (a) the planner
*choosing* them and (b) templates/exemplars that compose them per archetype.

## Goal (SP1)

Prompt apps get distinctive, app-appropriate **page archetypes** and declared
**domain features** — generated freely by the planner but **validated to be
renderable** — replacing CRUD-everywhere sameness, with zero new UI engineering
(reuse existing components) and no regression in the binding/CRUD reliability just
shipped.

## Decision: open with guardrails

The planner invents archetypes/features **freely** (open), but every choice is
**validated against a capability catalog**; un-renderable choices fall back to a
generic composition (never a broken page). This keeps creativity while avoiding
the "novel but broken" failure mode (hallucinated names / un-renderable nodes)
fixed earlier this session.

## Components

### 1. Capability catalog — `backend/services/app_design_catalog.py`

A machine-readable single source of truth.

- `ARCHETYPES: dict[str, ArchetypeSpec]` — each entry:
  `{components: list[str], template_key: str, exemplar_keys: list[str],
  renderable: bool, description: str, fits: str}`. Covers the 6 ready types plus
  the new ones in scope: `kanban`, `calendar`, `inbox` (split list+pane via
  InspectorPanel), `report` (Chart-led analytics), `wizard` (stepper/tabs),
  `audit-log` (Timeline/ActivityFeed), `settings` (tabbed/accordion config),
  `timeline`. Each new archetype's `components` are drawn ONLY from the existing
  registered set.
- `FEATURES: dict[str, FeatureSpec]` — each declared feature maps to an EXISTING
  primitive: `status-pipeline → status field + status-change workflow`,
  `approval → workflow`, `notify → workflow action`, `scheduled → timer node`,
  `rule/decision → decision table`. (Features needing NEW runtime — SLA-breach
  escalation, auto-reorder — are catalogued as `renderable_in: "SP2"` and the
  guardrail drops them in SP1.)
- `catalog_for_prompt() -> str` — compact names + one-liners injected into the
  planner prompt.
- `archetype_names() / feature_names() -> set[str]` — used by the guardrail.

Pure data + helpers; no I/O. Fully unit-testable.

### 2. Planner contract extension — `backend/agents/planner.py`

Extend `_ONESHOT_SYSTEM_PROMPT` (the headless path):

- Each `pages[]` entry gains `archetype` (string) and `features` (list of strings).
- Inject `catalog_for_prompt()` into the system prompt with instruction: *design*
  the app — for each page choose the archetype that fits its purpose (don't make
  everything a list), and propose the features that fit the entity, preferring
  catalog names. Keep `type` for backward compatibility (archetype is the richer
  signal; `type` still drives the legacy 6 templates as a fallback).
- (Interactive `PLANNER_SYSTEM_PROMPT` gets the same addition for parity.)

This is a prompt-contract change; verified via the planner-emits-archetype test
(mocked LLM) + the deterministic sanitizer below.

### 3. Guardrail / normalizer — `backend/services/app_design_guardrail.py`

Deterministic post-planner pass: `normalize_app_design(plan) -> (plan, report)`.

- For each page: if `archetype` not in `ARCHETYPES` or not `renderable` → map to
  the nearest known archetype (simple alias/keyword map) else fall back to the
  page's legacy `type` (or `generic`); record the substitution.
- Drop `features` not in `FEATURES` or marked `renderable_in: "SP2"`; record drops.
- Ensure every page has a valid `archetype` consistent with its `type` family.
- Returns the normalized plan + a `design_report` (per page: chosen archetype,
  substitutions, kept/dropped features). The pipeline writes
  `app-design-report.json`.

This is the "open with guardrails" guarantee. Pure function; TDD.

### 4. Archetype rendering catalog — templates + exemplars + rules

For each NEW archetype, make the schema agent compose it well:

- **Template**: add a skeleton to `backend/services/page_type_templates.py` (a
  composition of EXISTING components — e.g. kanban = `Stack{ Row{Heading, FilterBar},
  Kanban(bind, columns-by-status) }`; report = `Stack{ Row{Heading, DateRangePicker},
  Grid{Stat×N}, Card{Chart}, Card{Table} }`; inbox = `Split{ left: list, right:
  InspectorPanel }`; wizard = `Stack{ ApprovalStepper, Form(step fields), Row{Back,
  Next} }`; audit-log = `Stack{ Heading, Timeline }`; settings = `Tabs{ section
  forms }`).
- **Exemplar(s)**: 1+ golden `*.json` per archetype in
  `backend/fixtures/exemplars/`, validated against the Zod page schema.
- **Rules**: `schema_rules.py` entries for the archetype (e.g. "kanban: bind a
  list dataSource, group by the status field").
- **Wire `archetype` through**: `services/page_type.py` (accept explicit archetype
  override), `page_type_templates.template_for`, `schema_prompt.build_schema_prompt`
  (load archetype template+exemplars+rules), and `reference_bank` (load exemplars
  by archetype).

### 5. Page agent — `backend/agents/page_schema_agent.py`

Pass `page.archetype` into `build_schema_prompt(page_brief=...)` so the prompt
carries the archetype's template/exemplars/rules. (One-line plumbing; the prompt
builder does the work.)

### 6. Quick domain-mapping fix (folded in)

Fix the coarse-domain → Title-Case-key mismatch in `industry_design.py` by adding a
coarse→theme/layout alias map keyed on the planner's actual domain values:
`general→ocean`, `hr→hr`, `fintech→finance`, `healthcare→healthcare`, `saas→sharp`
(all are existing themes in `_THEME_COLORS`), with matching layout aliases. So
layout + theme stop collapsing to a single default. Small, high-impact, and
on-topic for "apps look alike."

### 7. Pipeline wiring

Run `normalize_app_design` right after the planner result (both
`_run_relay_pipeline` and `_run_figma_relay_pipeline` are prompt-capable; SP1
targets the prompt path — apply where the planner produces the plan, before schema
generation). Emit `app-design-report.json` at the output root.

## Data flow

```
prompt → planner (emits archetype + features, steered by catalog)
       → normalize_app_design (validate/normalize/fallback)  ← guardrail
       → per page: archetype → template + exemplars + rules → schema agent composes
       → existing binding + CRUD + completeness guard (unchanged)
```

## Error handling

- Un-renderable archetype → nearest-known or generic fallback + report entry.
  Never a broken page.
- Unsupported / SP2 feature → dropped + logged.
- Guardrail wrapped so a failure leaves the plan unchanged (degrade to today's
  behaviour), never aborts generation. Mirrors the binding pass's
  validate-or-fallback.

## Out of scope (SP1)

- New runtime engine features (SLA-breach escalation, auto-reorder, deadline
  routing) — that's **SP2**.
- IA / nav-grouping / dashboard-module selection variety — **SP3**.
- Figma path (it already differentiates from the design).
- New UI components (SP1 only composes existing ones).

## Testing

- `app_design_catalog`: archetype/feature specs present; helpers return expected
  names; new archetypes reference only registered components.
- `normalize_app_design` (TDD): unknown archetype → nearest/generic; SP2 feature
  dropped; valid passes through; report contents; failure leaves plan unchanged.
- Planner: deterministic sanitizer keeps valid archetype/features, drops invalid;
  prompt includes the catalog. (`planner.py` change verified via a pure sanitizer
  test, mirroring the existing `_sanitize_page_actions` pattern.)
- Archetype templates: each new template renders into a structurally-valid schema
  skeleton; exemplars validate against the Zod page schema.
- Live: two contrasting prompts (e.g. "help desk" vs "warehouse inventory")
  produce *different* archetypes/features, and `app-design-report.json` shows the
  choices — confirming distinctiveness without breakage.

## Success criteria

A prompt app no longer defaults to dashboard + list/detail/form everywhere: the
planner picks fitting archetypes (a board, a calendar, an inbox, a report…) that
render correctly from existing components, with features declared and validated,
and a `app-design-report.json` recording the design decisions — and the binding/
CRUD reliability is unchanged. Two different prompts visibly produce different
app structures.
