# Domain Form Intelligence

**Status**: spec'd, not implemented.
**Owner**: form-scaffolder + planner workstream.
**Companion**: `2026-08-07-brief-canonical.md` (visual authority — separate).

---

## Problem

Generated forms look and behave generic even when the underlying entity
has clear domain meaning. Live evidence: the property-mgmt "Add Rent
Payment" form (2026-08-07):

- Method dropdown shows raw enum keys (`"ach"`, `"pending"`) instead of
  human labels (`"ACH Transfer"`, `"Pending"`).
- Native browser date input (`dd/mm/yyyy` placeholder), not a real
  picker.
- Amount is a plain `type=number`, not formatted currency.
- Empty right rail — no lease context, no tenant chip, no balance,
  no payment history.
- Late Fee is a manual entry field instead of a computed value from
  lease terms × days late.
- Status field appears on a *create* form (confusing: recording a paid
  receipt vs. logging a pending charge is a mode question).
- No conditional revealing (ACH method should surface routing #, cash
  should surface receipt #, none does).
- Fields stack in one column even when natural pairs exist (due date +
  paid date).

None of this is a design problem — the visuals are irrelevant. The form
*scaffolder* has no idea rent payments are different from any other
CRUD.

## Solution

Six independently-shippable improvements to form authoring. Each closes
a specific class of gap. Any subset ships value; all six together move
generated apps from "runs and saves" to "feels like a real product."

## Non-goals

- No design/tokens/colors — that's `2026-08-07-brief-canonical.md`.
- No new LLM calls in the hot path — every fix is deterministic once
  planner emits richer metadata.
- No changes to the runtime dispatcher — form still submits to the
  same endpoints.

## Design

Six slices, ordered by dependency:

### Slice 1 — Enum human labels

**Problem**: dropdowns show `"ach"`, `"pending"`, `"credit_card"`.

**Fix**:
- Extend plan schema: `enum_values` becomes `[{key, label}]` instead of
  `[key]`. Backwards-compat: plain-string entries are auto-labeled via
  Title Case.
- Planner prompt: authored enums must include a `label` field.
- Form scaffolder / `Select` control read `label` for display, `key`
  for value.

**Touches**: `services/plan_normalizer.py`, `agents/planner.py` prompt,
`services/form_scaffold.py`, `packages/library/src/components/Select`.
~200 lines. 1 day.

### Slice 2 — Real date picker

**Problem**: native browser date input, no calendar UI, no locale
awareness.

**Fix**:
- Add `DatePicker` component to `@forge/library` (uses `react-day-picker`
  or in-house Calendar we already ship).
- Register in `buildDefaultRegistry` + `starter.json`.
- Form scaffolder: when column `type == "Date"` or `semantic_type ==
  "date"`, use `DatePicker` instead of `Input type="date"`.
- Same for `DateTimePicker` (combines with existing `TimePicker`).

**Touches**: `packages/library/src/components/DatePicker/` (new),
`packages/library/src/starter.ts`, `services/form_scaffold.py`,
`services/semantic_field_types.py`. ~350 lines. 1.5 days.

### Slice 3 — Formatted currency input

**Problem**: `Amount` is a plain number field. No `$`, no `,`
separators, not right-aligned, not tabular-nums.

**Fix**:
- Library already has `MaskedInput`. Add a `CurrencyInput` variant that:
  - Prefixes with locale currency symbol (`$` default, from brief or
    plan.locale).
  - Auto-formats thousands separator on blur.
  - Emits raw number to form state.
  - Renders right-aligned with `font-variant-numeric: tabular-nums`.
- Planner **must** emit `semantic_type: "money"` on money columns.
  Enforcement is prompt hardening + a plan validator that fails-loud
  when a `Numeric`/`Decimal` column has no `semantic_type` — no regex
  fallback. Regex catches English money-words and misses everything
  else (Arabic, French, domain-specific names). Prompt shows worked
  examples across domains; validator surfaces the column so planner
  gets a REVISE loop.
- Form scaffolder: money columns → `CurrencyInput`.

**Touches**: `packages/library/src/components/CurrencyInput/` (new),
`services/semantic_field_types.py` (regex fallback + prompt update),
`services/form_scaffold.py`. ~250 lines. 1 day.

### Slice 4 — Context side-rail (biggest slice)

**Problem**: forms that centrally reference a parent record (rent
payment → lease, appointment → patient, invoice → customer) have an
empty right rail. Users must remember or hunt for context.

**Fix**:
- New schema primitive: `context_panel` with `bindsTo: <fk field>`.
- Planner authoring rule: any form whose primary FK is `_primary=true`
  (new field-level flag) gets a `context_panel` sibling in the page
  layout, bound to that FK.
- New library component: `ContextPanel` renders a card that fetches
  the FK'd record + configured related-record lists.
- Deterministic authoring in `form_scaffold`: for each form, detect the
  most-important FK (heuristic: `_primary=true` if planner emitted it,
  else the FK with the most incoming relationships in the resource
  registry, else `NULL`). If found, insert a `context_panel`
  right-column child.
- Content of the panel: parent record's key fields (name, ID, status),
  a summary widget for the most-recent 3-5 related records
  (`.hasMany` on the parent), and a small stat if a numeric summary
  exists (e.g. lease.currentBalance).

Concrete for the rent-payment case: picking `Lease` → panel shows unit
number, tenant name, monthly rent, last 3 payments, outstanding balance.

**Touches**:
- `backend/schemas/plan.py` — new `context_panel` primitive.
- `backend/services/plan_normalizer.py` — pass-through validation.
- `backend/services/context_panel_builder.py` (new) — heuristic +
  authoring.
- `backend/services/form_scaffold.py` — insert panel into layout.
- `packages/library/src/components/ContextPanel/` (new).
- `packages/library/src/starter.ts` + registry.
- `packages/renderer/src/context-panel.ts` (new) — resolves bindings
  at runtime.

~800 lines. 3 days. **Highest UX payoff of the six slices.**

### Slice 5 — FK auto-fill (form interaction engine extension)

**Problem**: picking Lease should pre-fill Amount from
`lease.currentBalance` and Due Date from `lease.nextDueDate`.

**Fix**:
- Extend field-interaction engine's rule kinds to add
  `derive: { field: amount, source: "fk", fk: "leaseId", from:
  "currentBalance", when: "on_change" }`.
- Planner emits derivation rules per-form. Prompt guidance: "if a form
  has a primary FK and any field on the parent record could sensibly
  default the child form field, add a derive rule."
- Renderer's `form-interactions.ts` runtime resolves derive rules by
  fetching the FK'd record via the data engine when the FK dropdown
  changes.

**Touches**:
- `packages/renderer/src/form-interactions.ts` — new rule kind.
- `backend/services/form_interactions.py` — normalizer/validator.
- `backend/agents/planner.py` — prompt update.
- `backend/tests/services/test_form_interactions_derive.py` — new.

~300 lines. 1.5 days. Depends on Slice 4 (context panel and derive
both need reliable FK identification).

### Slice 6 — Conditional field sections

**Problem**: Method = ACH should reveal routing/account; Cash should
reveal receipt #; those extra fields exist nowhere.

**Fix**:
- Interaction engine already supports `show_if` on individual fields.
- Add `show_if` on `field_group` primitives so an entire subsection
  reveals conditionally.
- Planner prompt: when a form has an enum whose values imply different
  downstream data (payment method, task type, notification channel),
  author a `field_group` per branch with a `show_if` gate.

**Touches**: `packages/renderer/src/form-interactions.ts` (group-level
show_if), `services/form_scaffold.py`, `agents/planner.py` prompt.
~200 lines. 1 day.

### Slice 7 — Status semantics on create forms

**Problem**: Rent Payment has a `status` enum column (pending / paid /
overdue) that legitimately exists on the entity — but showing it as a
manual dropdown on the *create* form is confusing.

**Fix**:
- New field-level flag: `lifecycle_status=true` on status columns.
- Planner **must** emit `lifecycle_status: true` on columns whose
  values represent workflow state (as distinct from user-chosen enums
  like priority or category). Prompt hardening + plan validator that
  requires a decision on every enum column: `lifecycle_status: true`
  or `false`. No name-based fallback (`status`-named columns can mean
  different things in different domains).
- Planner also emits `default_value` on lifecycle columns (usually
  the enum's first value, but planner picks based on domain — a
  ticket defaults to `open`, a payment to `pending`).
- Form scaffolder: on *create* forms, hide `lifecycle_status` fields
  and use their `default_value`.
- On *edit* forms, expose the field as a proper status control
  (SegmentedControl or Badge picker, not raw dropdown).

**Touches**: `services/form_scaffold.py`, `services/plan_validator.py`,
planner prompt, `packages/library/src/components/StatusPicker/` (new
optional). ~250 lines. 1 day.

## Rollout (order + gates)

Each slice ships behind an env flag `FORGE_FORM_*=1`, default off:

1. **Slice 1 (enum labels)** — safest, additive to Select. Ship first,
   flag `FORGE_FORM_ENUM_LABELS`.
2. **Slice 2 (date picker)** — visible improvement, low risk.
   `FORGE_FORM_DATE_PICKER`.
3. **Slice 3 (currency input)** — low risk, semantic_type fallback
   catches missing planner metadata. `FORGE_FORM_CURRENCY`.
4. **Slice 7 (status semantics)** — small, isolated. `FORGE_FORM_STATUS`.
5. **Slice 6 (conditional sections)** — needs planner emission. Test
   with 3 domains before flag on. `FORGE_FORM_CONDITIONAL`.
6. **Slice 4 (context panel)** — biggest, most invasive. Ship last with
   two-week UAT soak. `FORGE_FORM_CONTEXT_PANEL`.
7. **Slice 5 (FK auto-fill)** — depends on 4. `FORGE_FORM_DERIVE`.

Order matters: don't ship 5 before 4 (both need FK-identification
plumbing); don't ship 4 before 1-3 (context panel benefit is muted
without human labels + real dates + currency).

Estimated total: **~8 engineering days** if run linearly, ~5 with
parallelism (slices 1/2/3/7 are independent).

## Testing

- Per-slice: unit + integration for the new schema primitives and
  runtime behavior.
- Live acceptance corpus: 4 domain apps (property mgmt, healthcare
  scheduling, HR onboarding, retail POS) regenerated after each slice
  lands. Screenshot diffs — the same "Add X" form should look
  substantially different at each slice milestone.
- Regression: existing 10-app UAT rotation must still build + pass
  self-verify.

## Rollback

Each slice's flag flips independently. If Slice 4 (context panel)
regresses, `FORGE_FORM_CONTEXT_PANEL=0` returns forms to their
Slice-1-2-3 shape without touching the others.

## Risks

- **Planner completeness**: Slices 1, 3, 5, 6, 7 all depend on planner
  emitting richer per-column metadata. Existing plans in DB won't have
  it. Mitigation: regex/heuristic fallbacks in scaffolder catch the
  common cases (money-named columns become CurrencyInput even without
  `semantic_type` set). Old plans work OK, new plans work great.
- **Context-panel binding failures**: if the parent record fetch 404s
  (deleted FK target), panel needs a graceful empty state. Design the
  runtime to render "Loading…" then "Not found" — don't blank the whole
  form.
- **Semantic vs syntactic status detection** (Slice 7): a column named
  `status` in one domain (kanban card) is different from `status` in
  another (invoice). Rely on planner tagging, not just column names,
  to decide `lifecycle_status`.
- **Library dist rebuilds**: Slices 2, 3, 4 add components. Each needs
  library dist rebuild + template re-vendor. Batch these into a single
  library release when possible.

## Follow-ups (out of scope)

- Bulk-edit / bulk-create forms.
- Optimistic-UI on submit (form disappears immediately, background
  reconciles).
- Inline field validation with domain-specific messages ("Amount
  exceeds outstanding balance").
- Form-level undo after submit.
