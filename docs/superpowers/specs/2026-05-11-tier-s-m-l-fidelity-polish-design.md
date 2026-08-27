# Tier S / M / L Fidelity Polish — Design

**Date:** 2026-05-11
**Status:** Draft for user review
**Predecessor specs:**
- `docs/superpowers/specs/2026-05-08-design-system-overhaul-design.md` — token taxonomy + register definitions (radius.scale, typography.scale, etc.)
- `docs/superpowers/specs/2026-05-08-enterprise-depth-design.md` — Tier 2/3 component additions
- `docs/component-token-audit.md` — per-component token consumption ground truth

This design closes the remaining **Tier S / M / L items** listed in `RESUME.md` as "~50% complete". The items are real-world polish that emerged while shipping Mark 2 / Mark 3 generations — they are individually small but collectively fix the gap between "schema renders" and "the result is visually credible at a designer's eye distance".

---

## 1. Goals

1. **Visual identity coherence.** A schema generated under any register (`default | workday | linear | stripe | notion | figma`) reads as that register's identity, not as a generic shadcn baseline. Today, radius / typography / CTA hierarchy collapse to defaults regardless of register.
2. **A11y baseline.** Every interactive library component has a keyboard path and a screen-reader label. Icon-only Buttons require `aria-label`; KeyValueList renders as `<dl>`/`<dt>`/`<dd>`; tab/arrow focus moves correctly through Tabs/Accordion/CommandPalette.
3. **Generation reliability on rich layouts.** The schema agent consistently chooses the right container (Accordion / Tabs / InspectorPanel / Card grouping) for forms and detail pages above ~7 fields. CTA variants follow a documented hierarchy, not the LLM's whim.
4. **Single, tractable design doc** — the items are correlated (radius → register; CTA hierarchy → schema prompt → Button) and benefit from shared sequencing rather than 3 separate specs.

## 2. Non-goals

- Adding new components. (That's Tier 2 wave 1-6, already shipping or shipped.)
- Reference-bank seeder prompt work. (Mentioned separately in `RESUME.md`, deferred — it's its own iterative research thread.)
- Schema-mode `seed.ts` compilation gap. (Also in `RESUME.md`; separate workstream — generated apps don't run with seeded data today, but that's a runtime concern, not a fidelity concern.)
- Visual diff viewer / cost dashboard / auto-promotion (those are design-system-overhaul Wave 5).

## 3. Item map — three workstreams

| # | Workstream | Item | Tier | Touches |
|---|---|---|---|---|
| 1 | **A. Library polish** | Radius scale unification | S | Library components (radius consumers) + register bundles |
| 2 | A. Library polish | Heading → type-scale classes | S | `packages/library/.../Heading.tsx`, `tailwind.config.ts` |
| 3 | A. Library polish | aria-labels on icon-only Button | M | Button schema + variants + validator |
| 4 | A. Library polish | Keyboard-nav audit | M | All ~55 library components; new test suite |
| 5 | A. Library polish | KeyValueList semantic markup | M | `KeyValueList.tsx` (HTML + Tailwind) |
| 6 | **B. Library API** | Icon prop on Button | L | Button schema, variant, scaffold registry, schema prompt |
| 7 | **C. Generation** | CTA hierarchy in design-spec | L | `design-spec.json`, `services/schema_prompt.py`, `services/schema_validator.py` |
| 8 | C. Generation | Progressive disclosure patterns | L | `services/schema_prompt.py`, validator, `backend/fixtures/exemplars/` |
| 9 | C. Generation | Schema-prompt proximity training | L | `services/schema_prompt.py` restructure |

**Workstream A** (items 1–5) ships in one library rebuild. Tight feedback loop: edit → `tsc` → scaffold reload.

**Workstream B** (item 6) extends A — same rebuild, but adds a schema + LLM-contract surface.

**Workstream C** (items 7–9) is generation-side. Each item is a prompt change that takes 5–15 minutes of generation work per iteration to evaluate. These ship behind the same generation pipeline, so they can be developed sequentially but tested together.

---

## 4. Workstream A — Library polish

### A1. Radius scale unification

**Decision:** `radius.scale ∈ { sharp | soft | round }` drives one radius for **all surfaces** (Card, Button, Input, Hero, Section, Alert, MetricTile, Tabs, …). Badges keep `rounded-full` always — pill shape is a semantic affordance, not a styling choice.

**Mapping:**

| `radius.scale` | Tailwind class | rem |
|---|---|---|
| `sharp` | `rounded-none` | 0 |
| `soft` (default) | `rounded-lg` | 0.5 |
| `round` | `rounded-2xl` | 1.0 |

The mapping is implemented as a **CSS custom property** on the document root, set by `TokensProvider` when the `radius.scale` token resolves:

```css
:root { --radius-surface: 0.5rem; }  /* soft */
:root[data-radius-scale="sharp"]  { --radius-surface: 0; }
:root[data-radius-scale="round"]  { --radius-surface: 1rem; }
```

Components reference the CSS var via a Tailwind arbitrary value: `rounded-[var(--radius-surface)]`. This keeps the Tailwind classname shape intact for IDE autocomplete + JIT, while letting the token override it at the document level without per-component prop drilling.

**Migration:**
1. Add the CSS-var emission to `TokensProvider` (`packages/library/src/theme/tokens-context.tsx`) — already has hooks; this is one new effect.
2. Replace every literal `rounded-md` / `rounded-lg` / `rounded-xl` in library components that style "surfaces" with `rounded-[var(--radius-surface)]`. Audit: ~14 components per the token-audit doc.
3. Badge stays at `rounded-full`. Avatar (which is a pill or circle by `shape` prop) is not affected.
4. `TokensProvider` reads `tokens.radius.scale` from its merged token snapshot and, in a `useLayoutEffect`, sets `document.documentElement.setAttribute("data-radius-scale", value)` (cleaning up on unmount). The CSS-var declarations live in a stylesheet shipped with `@tentoroforge/library` so consumers don't need to copy them.
5. Per-register defaults for `radius.scale` come from the existing register bundles in `packages/library/src/theme/registers/<name>.ts`: `linear` + `workday` → `sharp`, `stripe` → `soft`, `notion` + `figma` → `round`, `default` → `soft`. Each bundle already has `radius` as a partial override; we add `scale` to the existing field.

**Verification:**
- Visual-regression baselines update for each register × archetype combination (already part of `apps/visual-regression`).
- Snapshot test that asserts `<TokensProvider radiusScale="sharp"><Card/></TokensProvider>` emits class `rounded-[var(--radius-surface)]` AND the document root carries `data-radius-scale="sharp"`.

### A2. Heading → type-scale classes

**Decision:** `<Heading level={N}>` maps `level` (1-6) directly to Tailwind type-scale classes already defined in `apps/render-scaffold/tailwind.config.ts`:

| `level` | className |
|---|---|
| 1 | `text-page-title` (text-4xl tracking-tight) |
| 2 | `text-section` (text-2xl) |
| 3 | `text-card-title` (text-lg) |
| 4 | `text-body` (text-base) |
| 5 | `text-caption` (text-sm) |
| 6 | `text-micro` (text-xs) |

**Why direct mapping over the spec's `typography.display + typography.scale` model:** the type-scale tokens already exist in the scaffold's Tailwind config (RESUME.md notes they were added today). Adding a token-indirection layer now adds wiring without changing the rendered output. Register-level type-scale overrides can be added later by promoting the type-scale classes from the scaffold config into the library's `theme/registers/<name>.ts` bundles — that's a separate change with backward compatibility, not part of this work.

**Migration:**
1. Promote the type-scale classes from `apps/render-scaffold/tailwind.config.ts` into the library's own `tailwind.config.ts` (so they're available wherever the library is consumed, not just inside the scaffold).
2. Rewrite `packages/library/src/components/Heading/Heading.tsx` to drop inline `tokenToCssVar(SIZE_BY_LEVEL[level])` in favor of a `LEVEL_CLASS[level]` lookup.
3. Add a `weight` prop on Heading (`"display" | "regular"`) that maps to `font-bold` / `font-semibold` — small change that wires the existing `typography.display.weight` token without adding a new system.
4. Heading's existing `as` prop continues to control the rendered tag (`h1..h6`), independent of `level`.

**Verification:** snapshot tests on Heading at each level + register baseline screenshots.

### A3. aria-label requirement on icon-only Button

**Decision:** when the Button is icon-only (see B6: `icon` set, `label` absent), the rendered `<button>` must carry an `aria-label`. The library's Button schema (`packages/library/src/components/Button/Button.schema.ts`) gains a runtime `superRefine` that requires `aria-label` when `label` is absent.

**Behavior:**
- If `label` and `icon` both present → no requirement; the visible text is the accessible name.
- If `icon` present, `label` absent, `aria-label` absent → Zod parse error at the registry boundary. `LibraryDispatcher` falls back to the labelled placeholder ("Button missing aria-label").
- The error message in the placeholder is human-friendly; the schema-prompt addition in C7 tells the LLM to always emit `aria-label` for icon-only buttons.

**Why this strictness:** the renderer's existing fail-soft behavior keeps the page rendering when this fires (we don't crash a page over a missing a11y label), but the visible placeholder is loud enough that the schema author / LLM has feedback to fix it.

### A4. Keyboard-nav audit

**Decision:** add a single Playwright + axe-core test pass over the visual-regression fixtures. The test:

1. Loads each register × archetype fixture page already in `apps/visual-regression/`.
2. Tabs through every focusable element; asserts that focus order is meaningful (no traps, no skipped interactives, no focus on `aria-hidden` regions).
3. Runs `@axe-core/playwright` per page; fails on WCAG 2.1 AA violations of severity ≥ `moderate`.
4. Specifically covers: Tabs (left/right arrows move tabs), Accordion (Enter expands, arrows move between headers), CommandPalette (Esc closes, ↑↓ navigates, Enter selects), Select / MultiSelect (typeahead), DatePicker / DateRangePicker (arrow keys move date focus).

The audit produces a **single test file** with a per-component-area `describe` block. Failures point at specific files; fixes land per failure. Initial failures are expected (Tabs likely missing arrow-key handling); each fix is its own commit.

**Out of scope here:** screen-reader narration verification (no programmatic way to run NVDA / VoiceOver in CI). We rely on `aria-*` correctness for that.

### A5. KeyValueList semantic markup

**Decision:** `KeyValueList.tsx` swaps its current `<div className="divide-...">` tree for `<dl>` / `<dt>` / `<dd>`. Tailwind classes adjust to keep visual parity:

```tsx
// Before
<div className="divide-y divide-border">
  {items.map(({ label, value }) => (
    <div className="flex justify-between py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground">{value}</span>
    </div>
  ))}
</div>

// After
<dl className="divide-y divide-border">
  {items.map(({ label, value }) => (
    <div className="grid grid-cols-[1fr_2fr] gap-4 py-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{value}</dd>
    </div>
  ))}
</dl>
```

`<dl>` cannot directly contain flex/grid children per HTML5 spec; the row wrapper stays a `<div>` (the spec permits `<div>` between `<dl>` and its `<dt>`/`<dd>` children as of HTML5.2).

**Verification:** unit test that snapshots the rendered HTML and asserts the `<dl>` is present. Visual-regression baselines update.

---

## 5. Workstream B — Library API

### B6. Icon prop on Button

**Decision:** `<Button>` gains three new props:

| Prop | Type | Default | Notes |
|---|---|---|---|
| `icon` | `string` (Lucide name) \| undefined | undefined | Resolved via the existing `packages/library/src/icons/index.ts` resolver. Unknown names render a neutral placeholder icon. |
| `iconPosition` | `"left" \| "right"` | `"left"` | Ignored when `label` is absent. |
| `aria-label` | `string` | undefined | Required when icon-only (see A3). |

**Schema (`Button.schema.ts`):**

```ts
export const ButtonProps = z.object({
  label: z.string().optional(),
  icon: z.string().optional(),
  iconPosition: z.enum(["left", "right"]).default("left"),
  variant: z.enum(["primary", "secondary", "ghost", "danger"]).default("primary"),
  size: z.enum(["sm", "md", "lg"]).default("md"),
  navigate: z.string().optional(),
  "aria-label": z.string().optional(),
  // …existing fields
}).superRefine((data, ctx) => {
  if (!data.label && !data["aria-label"]) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "icon-only Button requires aria-label",
      path: ["aria-label"],
    });
  }
});
```

**Variant impact:** the Button's `variants.ts` CVA factory grows a slot for the icon (sets `gap-2`, sizing). Icon-only renders without the gap. Icon size scales with Button `size`: `sm → 14px`, `md → 16px`, `lg → 20px`.

**Registry remap layer:** the existing `unifyLabelHref` already accepts `content` / `children` as label aliases. Add `iconName` → `icon` if the LLM emits the longer form (cheap insurance).

**Schema prompt addition:** the schema_prompt.py block that lists Button props gains an `icon` and `iconPosition` example, plus the rule "icon-only Buttons MUST set aria-label".

---

## 6. Workstream C — Generation / prompt training

### C7. CTA hierarchy in `design-spec.json`

**Decision:** `design_agent` writes a `cta_hierarchy` block into `src/contracts/design-spec.json` as part of its existing design-spec emission. When `design_agent` is skipped (e.g., legacy paths that go directly from planner → schema), the pipeline injects per-register defaults via a new `services/cta_defaults.py::defaults_for_register(register)` helper, written to design-spec by the same code that handles the existing `register` field. The register name continues to be picked by `services/register_selector.py` (unchanged).

```json
{
  "register": "linear",
  "cta_hierarchy": {
    "primary":   { "variant": "primary",   "max_per_page": 1, "min_per_page": 1 },
    "secondary": { "variant": "secondary", "max_per_page": 3, "min_per_page": 0 },
    "tertiary":  { "variant": "ghost",     "max_per_page": null, "min_per_page": 0 }
  }
}
```

The block has **per-register defaults** baked in (`linear` / `workday` favor `secondary` outline-style; `stripe` / `figma` favor `primary` filled). The design_agent picks the defaults from the register and the planner's per-page archetype; the user can override later via the design panel.

**Schema-prompt consumption:** `services/schema_prompt.py::build_schema_prompt()` reads `cta_hierarchy` and injects a rule block:

```
## CTA hierarchy (binding)
- Every page MUST have exactly 1 Button with variant="primary".
- Use variant="secondary" for follow-up actions (max 3 per page).
- Use variant="ghost" for tertiary or inline actions (no limit).
- Place the primary CTA in the hero / top-right of the page where visual weight expects it.
```

**Validator (`services/schema_validator.py`) gains a count check** (`validate_cta_hierarchy(schema, design_spec)`):
- Counts Button nodes by variant.
- Fails (raises `SchemaValidationError`) when `primary` count < 1 or > 1.
- Fails when `secondary` count > 3.
- Surfaces failures via the existing `phase_gates.py` retry loop — `feature_slice_schema_agent` re-runs with a `fix_prompt` that quotes the violation.

**Per-page exception:** form pages (`page_type == "form"`) skip the `primary` count check — the form's submit button is the implicit primary CTA but may not be a top-level Button node (could be inside `<Form>`). The validator treats `<Form>` as providing a primary CTA.

### C8. Progressive disclosure schema patterns

**Decision:** three layers, shipping together.

**Layer 1 — Prompt rules** in `services/schema_prompt.py`:

```
## Container choice (binding)
- Form with > 7 user-editable fields: wrap in Accordion (collapsed panels per logical group)
  or Tabs (one tab per group). Pick Accordion when groups have a sequence; Tabs when they don't.
- Detail page with > 5 sections of content: use Tabs (or TabPanelWithDeepLink) to split.
- "View row → see detail" interaction: prefer InspectorPanel over a separate detail page.
- Related field cluster (3-6 fields that belong together semantically): wrap in Card.
- NEVER lay out > 10 form fields in a flat Stack — readers cannot scan that density.
```

**Layer 2 — Validator** in `services/schema_validator.py` (`validate_progressive_disclosure(schema)`):
- Walks the tree; counts Input/Select/Textarea/Checkbox/DatePicker descendants per Form.
- Fails if a Form has >7 fields not partitioned into Accordion or Tabs.
- Fails if a detail page (`page_type == "detail"`) has >5 Section children at the page root level (suggests Tabs).
- Like the CTA validator, surfaces via the retry loop.

**Layer 3 — Reference exemplars** in `backend/fixtures/exemplars/`:
- 3–5 hand-authored exemplar schemas covering: "wide form (9 fields → Accordion)", "detail page with 6 sections → Tabs", "list row → InspectorPanel", "related-fields cluster → Card", "narrow form (4 fields → flat Stack)".
- `schema_prompt.py` cites these by file name in a "## Reference patterns" block. The exemplars are inlined into the prompt (small — ~30 lines each).

**Iteration loop:** the design ships, then is tuned by running 10–20 generations through the existing fidelity loop and reading vision-evaluator scores. Each iteration is a tweak to one of the three layers. The validator + exemplars + rules form a coordinated whole — they should evolve together.

### C9. Schema-prompt proximity training

**Decision:** restructure `services/schema_prompt.py::build_schema_prompt()` so each binding rule is followed immediately by a tiny (5–15 line) correct example and then by the entity context the rule applies to. The current monolithic "## Rules" block becomes a sequence of `## Rule: <name>` sections, each self-contained.

**Before / after sketch (concrete in the previous question's preview).**

**Implementation steps:**
1. Catalogue the existing rules in `schema_prompt.py` into a Python data structure: `RULES: list[Rule]` where each `Rule` has `name`, `body`, `example_snippet`, `applies_when(entity, page_type)`.
2. The rule list lives in a new module `services/schema_rules.py`. Each rule is a dataclass; `build_schema_prompt()` iterates and emits.
3. The new structure makes it easy to A/B test by toggling rules — add a debug-only `RULES_DISABLED: set[str]` env var.
4. Token budget check: the rule list + entity context must fit in Sonnet's reliable-attention window (~30k tokens conservatively). Add a check that warns if the prompt exceeds 25k tokens.

**Verification:** run 5–10 generations against existing test entities (`output/<test-id>/...`); compare vision-evaluator scores against the previous-prompt baseline. If proximity-training drops scores, revert and document.

**Risk note:** prompt restructuring can regress on dimensions the evaluator doesn't measure. Manual eyeballing of the first 3–5 generations is part of the verification, not just numeric scores.

---

## 7. Sequencing + dependencies

```
A1 Radius scale ──┐
                  ├──► A4 Keyboard nav audit (uses updated baselines)
A2 Heading       ─┤
A3 aria-label    ─┤
A5 KeyValueList  ─┘

B6 Button icon  ──► depends on A1 (radius var) for icon-only round button
                    enables A3's icon-only path
                    feeds C7's variant taxonomy and C8/C9's rule examples

C7 CTA hierarchy ──► depends on B6 (Button.icon) and design-spec emission
C8 Progressive   ──► depends on C7 (shares validator + retry loop infra)
C9 Proximity     ──► depends on C7 + C8 (rules to interleave must exist)
```

**Recommended implementation order:**

1. **A1 + A2** together — both touch library + Tailwind config, common build cycle.
2. **A5** — small, contained.
3. **B6** — Button icon prop. Lands the prop, schema, variants, registry registration.
4. **A3** — now that icon-only is a real shape, the aria-label requirement makes sense. Add the schema refine.
5. **A4** — keyboard-nav audit. Runs against updated A1+A2+A3+A5+B6 state. Failures surface as a punch list of small fixes.
6. **C7** — CTA hierarchy in design-spec + schema prompt + validator. Validates against the existing test projects.
7. **C8** — progressive disclosure patterns. Reuses C7's gate infrastructure.
8. **C9** — proximity training restructure. Last because it touches the same prompt file as C7/C8 and bundling them risks complex diffs.

Items 1–5 are A+B and finishable in one session if focused. Items 6–8 are C and benefit from a separate session with the generation pipeline running.

## 8. Testing strategy

| Item | Tests added |
|---|---|
| A1 | Snapshot test on radius CSS-var emission + visual-regression baselines |
| A2 | Snapshot per Heading level + visual-regression baselines |
| A3 | Schema-validation unit test: parse fails when `icon` set, `label` absent, `aria-label` absent |
| A4 | Playwright + axe-core suite over visual-regression fixtures; one test per fixture |
| A5 | Snapshot test asserting `<dl>` / `<dt>` / `<dd>` present in rendered output |
| B6 | Schema unit tests for new props + variants.ts snapshot |
| C7 | `validate_cta_hierarchy` unit tests for under/over count cases; generation smoke test on existing project |
| C8 | `validate_progressive_disclosure` unit tests; one generation per exemplar |
| C9 | Snapshot of `build_schema_prompt(test_plan)` output; token-budget assertion |

All tests run in CI alongside the existing `packages/{schema,renderer,library}` suites.

## 9. Risks

- **CSS-var radius indirection (A1)** is one more layer of CSS-var rocket science that bites when authors don't realise classes resolve dynamically. Mitigated by the documented Tailwind class shape; auditing via codegrep for any literal `rounded-md`/`rounded-lg`/`rounded-xl` post-migration.
- **Validator strictness (C7, C8)** can regress generation throughput — if the LLM can't reliably satisfy the CTA / progressive-disclosure gates, the retry loop fires forever. Mitigated by capping retries at 2 in `phase_gates.py` (current behavior) and degrading to a `log` event when the cap hits, not a hard fail.
- **Proximity restructure (C9)** could regress on dimensions the vision evaluator doesn't measure (e.g., terseness, semantic correctness of bindings). Mitigation: manual review of first 3–5 generations; revert flag prepared.
- **A11y audit (A4)** may surface a long tail of small issues (Radix primitives in Tabs/Accordion may need wiring we haven't done). Scope risk; we accept that A4 may take a second session of fix-up work.
- **Button schema migration (B6)**: existing schemas in `output/<project>/src/schemas/**` may emit Button differently. The registry's `unifyLabelHref` remap layer mostly handles this, but the new `aria-label` requirement could fail older schemas. Mitigation: validator failure renders the placeholder, not a crash — older schemas keep loading.

## 10. Out of scope / deferred

- Reference-bank seeder prompt work (RESUME.md item 4). Iterative research; separate brainstorm when ready.
- Schema-mode `seed.ts` compilation gap (RESUME.md item 5). Engineering, not fidelity.
- Per-register typography scale overrides (would change A2's mapping per register). Future work, additive to A2.
- Comprehensive RTL support. Tier 2 wave concern.
- Per-page custom CTA hierarchy override (allow design-spec to vary CTA rules per page archetype). Possible later; current scope is project-wide rules.

---

## 11. Implementation hand-off

This design will hand off to `writing-plans` for a per-item implementation plan. The plan will sequence the 9 items in the order from Section 7 and produce checkpointed task lists for each.
