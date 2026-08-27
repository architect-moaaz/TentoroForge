# Domain-Intelligence Bypass Cleanup

**Status**: spec'd, not implemented.
**Owner**: platform-quality workstream.
**Companions**:
- `2026-08-07-brief-canonical.md` (Spec A — visual fidelity)
- `2026-08-07-domain-form-intelligence.md` (Spec B — form UX)
- `2026-08-07-design-polish.md` (Spec C — dashboards/voice/motion)

Retires ~4000 lines of hand-authored per-industry Python and replaces
them with the "LLM authors structured intent + deterministic renderer
validates against real registries" spine used everywhere else in the
platform. Six waves, each ships independently.

---

## Problem

An audit (2026-08-08) found **22 anti-patterns** across ~10 files
totalling ~4000 lines of per-domain Python code. Every one follows the
same shape:

> The LLM was unreliable for decision X, so someone wrote a Python
> catalog / classifier / rule-table with a fixed vocabulary. New
> domains fall through to a "default" bucket; adding coverage means a
> Python PR.

Concrete examples from the audit (all in `backend/services/`):

- [design_dna.py:252](backend/services/design_dna.py:252) — `ARCHETYPES`
  dict with 14+ industry personalities (hues, saturation, font
  pairings, principles); novel domain → "default-saas".
- [design_dna.py:616](backend/services/design_dna.py:616) — `AUTH_COPY`
  per-industry sign-in taglines; every fintech app rotates the same 2.
- [design_dna.py:660](backend/services/design_dna.py:660) —
  `_BRAND_FRAGMENTS` per-industry product-name words; nursery
  marketplace gets Ledger/Vault.
- [domain_ux_specs.py:22](backend/services/domain_ux_specs.py:22) — 795
  lines, only 7 named industries, hardcoded literal column names
  (`mrn`, `dob`, `primary_physician`).
- [design_language.py:40](backend/services/design_language.py:40) — 1165
  lines. 8 hardcoded design axes (NAV_SHAPES, ACTIVE_MARKS, etc.) with
  pairwise compatibility rules.
- [commerce_flag.py:41](backend/services/commerce_flag.py:41) —
  `_COMMERCE_VERBS` word list; "monthly retainer" fails.
- [dual_meaning_domain.py:31](backend/services/dual_meaning_domain.py:31)
  — 30 hardcoded dual-meaning nouns; "tattoo parlour" invisible.
- [fk_semantics.py:24](backend/services/fk_semantics.py:24) —
  actor/assignment/tenancy role by column-name regex.
- [scheduler_pass.py:18](backend/services/scheduler_pass.py:18) —
  resource-vs-person word lists; "AircraftSlot" misses.
- [semantic_field_types.py:41](backend/services/semantic_field_types.py:41)
  — 6+ regex classifiers + `_CURATED_ENUM_VALUES` that overwrite what
  planner authored.
- [figma_name_classifier.py:31](backend/services/figma_name_classifier.py:31)
  — 100+ hardcoded name→schema-type rules.
- [nav_icon_map.py:22](backend/services/nav_icon_map.py:22) — HR-flavored
  icon buckets; pottery app gets `folder`.
- [intent_classifier.py:66](backend/services/intent_classifier.py:66) —
  closed 17-intent taxonomy × fixed tool subsets.
- [task_assignment_strategies.py:45](backend/services/task_assignment_strategies.py:45)
  — closed 9-strategy enum with hardcoded SQL against invented columns.
- [cta_defaults.py:15](backend/services/cta_defaults.py:15) — 6-brand
  `Literal` register vocab; half entries are `_BASE`.
- [design_brief.py:24](backend/schemas/design_brief.py:24) — Voice (5)
  / Radius (3) / Density / NeutralTint enums bucketize continuous
  vocabularies.
- [section_templates.py:7](backend/services/section_templates.py:7) — 15
  curated section prompt templates.
- [shell_templates.py](backend/services/shell_templates.py) — 785 lines,
  3 hardcoded shell frames.
- [archetype_page_fixes.py:1](backend/services/archetype_page_fixes.py:1),
  [archetype_detector.py:26](backend/services/archetype_detector.py:26),
  `services/archetypes/*.py` — per-archetype closed catalogs.
- [payment_feature.py:30](backend/services/payment_feature.py:30),
  [user_fk_types.py:29](backend/services/user_fk_types.py:29),
  [page_type_classifier.py:17](backend/services/page_type_classifier.py:17),
  [figma_action_classifier.py:33](backend/services/figma_action_classifier.py:33)
  — additional keyword classifiers.

**The deeper problem**: code comments in the biggest offenders
(`shell_templates`, `design_dna`, `design_language`) explicitly say
*"the LLM was unreliable, so this module replaces guesswork with a
curated space"*. The healthy pattern (`resource_registry`,
`archetype_classifier`'s LLM-refinement path, planner authoring form
field-specs) already exists in the platform — but wasn't the default.

## Solution

Six waves, each replaces one class of the bypass layer with the
platform's standard spine: LLM authors structured plan/brief output,
deterministic renderer validates against real registries.

## Non-goals

- No new bypass layers. If a wave finds LLM output too weak for a
  decision, the fix is prompt hardening + validator + REVISE loop, not
  a new Python catalog.
- No changes to the healthy patterns (`resource_registry`, planner
  authoring, `archetype_classifier` LLM-refinement path).
- No changes to Spec A/B/C — this spec strips the bypass layer; those
  three ship the new authorities. Run this spec in parallel or after.

## Non-negotiables (spans all waves)

- **Every retired classifier gets a fail-loud replacement in the
  planner or brief author.** Silent regex fallbacks are the failure
  mode this spec closes; adding a new one anywhere is a rejection
  criterion for a PR.
- **Deterministic renderers may exist; deterministic *authors* may
  not.** A pass that maps `brief.motion.duration_fast_ms` to a CSS
  variable is fine (mechanical). A pass that decides motion feel from
  domain keywords is not.
- **Registries stay open-ended.** Component registry, entity registry,
  workflow registry — all read from what code exists / plan declares,
  never from a curated per-domain list.

## Design

### Wave 1 — Design authorship consolidation (biggest, ~5-7 days)

**Retires**:
- `services/design_dna.py` — 1968 lines, three per-industry dicts
- `services/design_language.py` — 1165 lines, hardcoded compositional axes
- `services/domain_ux_specs.py` — 795 lines, per-industry UX playbook

**Replaces with**:
- Brief author (already exists) emits richer structured output:
  - `visual_stance: {hue_range, temperature, shape_vocab, principles}`
    — replaces `ARCHETYPES` per-industry personality lookup
  - `auth_taglines: [str, str]` — replaces `AUTH_COPY` per-industry
    rotation
  - `product_name_candidates: [str]` — replaces `_BRAND_FRAGMENTS`
    word-fragment generator (planner also emits final choice)
- Planner emits per-page `ux_hint: {hero_fields, key_widgets, empty_state, info_hierarchy}`
  grounded in the actual entity registry — replaces `DOMAIN_UX`
  hardcoded columns
- Design agent emits **concrete numeric+string design DNA**
  (`radius_px`, `gutter_px`, `header_align`, `card_border`, `shadow_scale`)
  instead of picking from `NAV_SHAPES` / `ACTIVE_MARKS` / `HEADER_STYLES`
  closed alphabets. Deterministic compiler validates against a
  capability envelope (range checks), not a pairwise-compatibility
  table.

**Files**:
- **Delete**: `services/design_dna.py` (1968 lines),
  `services/design_language.py` (1165 lines),
  `services/domain_ux_specs.py` (795 lines)
- **New**: `services/design_capability_envelope.py` (~150 lines) —
  range validators (`radius_px in [0,32]`, `gutter_px in [4,64]`, etc.)
- **Extend**: `schemas/design_brief.py` — new fields
  (`visual_stance`, `auth_taglines`, `product_name_candidates`)
  (~80 lines)
- **Extend**: planner prompt + plan schema — `page.ux_hint` field
  (~60 lines)
- **Extend**: design agent (or its brief-canonical successor) — richer
  emission (~120 lines)
- **Callers**: whoever currently reads the three dicts — update to
  read the new fields (~200 lines across ~8 files)
- **Tests**: schema fixtures + capability envelope tests (~400 lines)

Net: **~4000 lines removed, ~1000 lines added**. Biggest cleanup in
the spec.

### Wave 2 — Semantic classifier retirement (~4-5 days)

**Retires 8 keyword classifiers**:
- `services/commerce_flag.py`
- `services/dual_meaning_domain.py`
- `services/payment_feature.py`
- `services/fk_semantics.py` (regex fallback path)
- `services/user_fk_types.py` (allowlist path)
- `services/scheduler_pass.py`
- `services/page_type_classifier.py`
- `services/semantic_field_types.py` (regex + `_CURATED_ENUM_VALUES` path)

**Replaces with per-column / per-page / per-app plan fields**:
- `entity.commerce: {is_commerce, primary_product_entity?}` — planner emits
- `discovery.needs_disambiguation: {question, options}` — discovery emits
  when domain is ambiguous
- `entity.needs_payment_methods: bool` — planner emits
- `column.role: "actor" | "assignment" | "tenancy" | "domain"` —
  planner emits explicitly per FK column
- `page.widget_hint: str` (open string, validated against component
  registry) — planner emits
- `page.page_type` — already exists; classifier just trusts it
- `column.semantic: {control, enum_values?, format?}` — planner emits
  per column

**Enforcement pattern**: each retired classifier is replaced with a
plan-validator rule that fails loud when the corresponding field is
missing. No silent regex fallback.

**Files**:
- **Delete**: all 8 modules (~1500 lines total)
- **Extend**: `schemas/plan.py` — new fields per the list above (~150 lines)
- **Extend**: `services/plan_validator.py` — 8 new rules (~200 lines)
- **Extend**: `agents/planner.py` — prompt hardening + worked examples (~180 lines)
- **Callers**: whoever reads these classifiers — update to read plan
  fields directly (~300 lines across ~15 files)
- **Tests**: validator tests + planner emission tests (~500 lines)

Net: **~1500 lines removed, ~1000 lines added**. Second-biggest wave.

### Wave 3 — Rule-table retirement (~2 days)

**Retires 3 closed vocabularies**:
- `services/task_assignment_strategies.py` — closed 9-strategy enum +
  hardcoded SQL against invented columns
- `services/intent_classifier.py` — closed 17-intent × fixed tool subsets
- `services/cta_defaults.py` — `RegisterName = Literal[…6…]` + per-register
  `CtaHierarchy`

**Replaces with**:
- Task assignment: planner emits `user_task.assignee: {kind, sql? | role? | column?}`
  per user_task at plan time — SQL is authored by the LLM against real
  registry columns, not invented ones. Runtime executes verbatim.
- Intent classification: LLM emits `needed_domains: [str]` from an open
  list; tool subset derived from a `tool_tag → tools` index. LLM never
  picks tool names directly (existing safety property preserved).
- CTA hierarchy: brief author emits concrete `{primary, secondary,
  tertiary}` `{max_per_page, min_per_page, variant}` — nine fields, no
  register name.

**Files**:
- **Refactor**: 3 modules become thin lookup/validator layers, ~50 lines each
- **Extend**: plan/brief schemas — new fields (~80 lines)
- **Extend**: planner + brief-author prompts (~120 lines)
- **Tests**: (~200 lines)

Net: **~500 lines removed, ~500 lines added**. Smaller wave, closes a
sharp irregularity (invented SQL columns).

### Wave 4 — Constrained-enum liberation in brief schema (~1 day)

**Retires**: `Voice` (5), `Radius` (3), `Density` (4), `NeutralTint` (3)
enums in `schemas/design_brief.py`.

**Replaces with concrete fields**:
- `voice: str` — free-form, capped at 40 chars
- `radius_px: int` — 0..32 validated range
- `density_pt: int` — 0..32 validated range (pixel-scale spacing unit)
- `neutral_tint: str` — free-form, capped at 20 chars (LLM can say
  "cool with green undertone")

Deterministic compiler snaps to renderable values (nearest CSS token)
without discarding the LLM's semantic authoring.

**Files**:
- **Modify**: `schemas/design_brief.py` (~40 lines)
- **Modify**: brief-author prompt (~30 lines)
- **Modify**: `brief_to_design_spec.py` — snap-to-nearest helpers (~50 lines)
- **Migrate**: existing cached briefs (may re-author on first read after
  deploy)
- **Tests**: (~100 lines)

Net: **~40 lines removed, ~120 lines added**. Small cleanup, unblocks
Spec A + Spec C without artificial buckets.

### Wave 5 — Figma classifier LLM-ification (essential for Figma fidelity, ~2-3 days)

**Non-negotiable pairing with Spec A**: Spec A's "zero Figma palette
drift" contract only covers visual tokens. Layer names + actions +
icons are the *structural* half of Figma fidelity — if a designer
names a checkbox "Selectable" and today's classifier maps it to `Box`,
the rendered app doesn't match the Figma even if colors do. This wave
closes that structural gap by applying the same LLM-authored intent +
registry-validated pattern to Figma imports.

**Retires 3 Figma-side keyword classifiers**:
- `services/figma_action_classifier.py` — `_NAV_LABELS` bearing traces
  of one specific CRM Figma
- `services/figma_name_classifier.py` — 100+ hardcoded name→schema-type
  rules
- `services/nav_icon_map.py` — HR-flavored icon buckets

**Replaces with LLM classifier passes** grounded in real registries:
- `services/figma_action_llm.py` — LLM reads label + surrounding
  context + target plan's routes/workflows, emits binding grounded in
  what exists
- `services/figma_name_llm.py` — LLM reads name + Figma node type +
  neighbors + component registry, picks from registered components
- `services/nav_icon_llm.py` — planner (or brief author) picks icon
  from a 60-icon Lucide subset the shell renders (closed *icon set*
  is fine — the *decision* is LLM-driven, and the icon set is
  infrastructure not domain intelligence)

Same shape as the existing `archetype_classifier` LLM-refinement path.
Falls back to "unknown → skip" rather than silent misclassification.

**Files**:
- **Delete**: 3 modules (~700 lines total)
- **New**: 3 LLM-classifier services (~200 lines × 3 = ~600 lines)
- **Tests**: (~300 lines)

Net: **~700 lines removed, ~900 lines added**. Small net growth
because LLM callers need more scaffolding, but delivers open coverage.

### Wave 6 — Template/section catalog consolidation (~2 days)

**Retires**:
- `services/section_templates.py` — 15 curated section prompt templates
- `services/shell_templates.py` — 785 lines, 3 hardcoded shell frames
  (paralleling `design_language.NAV_SHAPES` post-Wave-1)

**Replaces with**:
- Sections: code-editor agent authors each section directly from
  category + surrounding page context, no template pool
- Shells: bridge into Wave 1's design-agent numeric+string emission
  (which already produces varied shell shapes); delete the parallel
  three-shape catalog

**Files**:
- **Delete**: 2 modules (~1000 lines total)
- **Extend**: code-editor agent prompt (~80 lines)
- **Bridge**: design-agent → shell-render (~150 lines)
- **Tests**: (~200 lines)

Net: **~1000 lines removed, ~430 lines added**. Real cleanup, mostly a
consequence of Wave 1 landing.

## Rollout

Each wave ships behind `FORGE_CLEANUP_WAVE_*` flag, default off. When
a wave's flag is on:
- The new plan/brief fields become required (validator fails loud if
  missing).
- The retired module's callers use the new field.
- Deletion of the retired module happens **one release after** the flag
  is default-on (safety soak).

**Recommended order (dependency + risk)**:
1. **Wave 4** (enum liberation) — smallest, unblocks A + C ergonomically
2. **Wave 3** (rule-table retirement) — small, closes SQL-column
   invention (correctness win)
3. **Wave 2** (semantic classifier retirement) — biggest correctness
   win; enables Spec B to drop its regex fallbacks
4. **Wave 1** (design authorship consolidation) — biggest cleanup;
   requires Spec A to have shipped so brief is canonical
5. **Wave 5** (figma classifier LLM-ification) — must ship for Figma
   fidelity to hold; runs in parallel with any other wave; needs
   Figma-fixture corpus for testing (3+ real projects with varied
   layer-naming conventions)
6. **Wave 6** (template consolidation) — must land after Wave 1
   (bridges into it)

**Sequencing with Specs A/B/C**:
- Wave 2 should ship BEFORE Spec B — otherwise Spec B has to write
  regex fallbacks it will later strip.
- Wave 1 should ship AFTER Spec A — Spec A makes brief canonical;
  Wave 1 puts more content into the canonical brief.
- **Wave 5 should ship WITH Spec A** — Spec A locks in Figma palette
  fidelity; Wave 5 closes the structural half (layer→component,
  label→route, icon selection). Ship them together or the "Figma
  fidelity" claim is only half true.
- Wave 4 is independent — ship any time.

**Total scope**: ~16-20 engineering days linear, ~8-10 with
parallelism. Comparable to Spec C.

## Testing

- Per-wave: unit tests for new plan/brief fields, validator rules,
  planner emission (with fixture corpus of 6+ novel domains — not the
  6 anchors, actually novel).
- **Cross-domain acceptance**: after each wave, regenerate 5 novel
  domain apps not covered by any prior curated list ("tattoo parlour
  booking", "brewery inventory", "aircraft slot scheduling", "pottery
  kiln batches", "vet clinic marketplace"). Verify:
  - No fields are `[missing]` or default-bucket-fallback
  - Every deleted classifier's decision now traces to a plan/brief
    field authored by the LLM
- **Regression corpus**: existing 10-app UAT rotation must still build
  + pass self-verify.

## Rollback

Each wave's flag flips independently. If Wave 2 (semantic classifiers)
regresses:
- `FORGE_CLEANUP_WAVE_2=0` restores the classifiers
- Deleted modules are frozen at `services/_legacy_classifiers/*.py` for
  30 days post-deletion; flag flips restore them from that path

## Risks

- **Planner won't reliably emit rich structured output** — this is the
  central bet of the whole spec. Mitigation: prompt hardening + fixture
  test corpus for each new field + fail-loud validators that force a
  REVISE loop. If a specific field proves persistently hard to emit,
  audit the prompt; do NOT reintroduce a Python fallback.
- **Migration disruption for existing projects** — apps generated
  before a wave lands don't have the new plan/brief fields.
  Mitigation: each retired module keeps a read-only "legacy plan
  compatibility" branch for 30 days; new generations use the new
  fields.
- **Test brittleness on novel domains** — the whole point is that
  novel domains work, so the acceptance corpus must genuinely be
  novel. Rotate the corpus each release; don't calcify on 5 fixed
  novel domains.
- **Wave 1 depth** — design_dna + design_language + domain_ux_specs
  is ~4000 lines with unknown call sites. Do a call-graph audit at
  the start of Wave 1 to enumerate readers before deleting.

## The deeper principle (why this matters)

Every anti-pattern in this spec exists because someone at some point
decided **"the LLM was too unreliable for this, so I'll write a
Python catalog."** That decision was locally correct — the resulting
code often worked better than the LLM at that moment. But it
compounded into a bypass layer: 4000 lines of curated per-domain
intelligence that silently fails for every domain not in the curated
list.

The platform-level fix is a **discipline**, not a spec: whenever the
LLM produces weak output, the fix is prompt hardening + validator +
REVISE loop against real registries. Never a new Python catalog.

Adding this principle to the review checklist for new PRs is more
important than any single wave in this spec.

## Follow-ups (out of scope)

- Review checklist / lint rule that flags new `_MAP = {...}` and
  `INDUSTRY_*` and closed `Literal[...]` in service code.
- Metrics dashboard: "planner-emission completeness rate per field" —
  surface which new plan/brief fields planner routinely misses so
  prompts can be hardened.
- Structural refactor: move all planner-emitted plan fields into
  `schemas/plan.py` (single authority); avoid future drift where
  fields are added by string manipulation in agent prompts.
