# Form Interaction Engine — Spec (item 5)

## Problem
Generated forms are static: every field is independent. Real forms are reactive:
- **Computed fields** — `totalCost = ratePerDay × daysBetween(startDate, endDate)`; a field's value is derived from siblings and recomputes as they change.
- **Dependent dropdowns** — selecting `categoryId` fetches/filters the `productId` options; selecting a customer populates their address.
- **API-populated selects** — options fetched from a resource, optionally filtered by another field.

And the user must be able to **author these interactions from the editor UI** (`:6501`), not just receive them from generation.

## Principle
A declarative **field-interaction contract** on the form schema + a **reactive form controller** in the renderer that evaluates it, + an **editor panel** to author it. Reuse the existing expression engine (feel-lite / `bindings.ts` `evalExpression`) for formulas — do not invent a new language. Deterministic auto-derivation seeds the obvious cases; the editor lets the user do the rest.

## The contract (form field schema additions)
Per form field node, an optional `interaction` block:
```jsonc
// computed / derived field (read-only, value from a formula over sibling fields)
"interaction": {
  "computed": {
    "formula": "ratePerDay * daysBetween(startDate, endDate)",  // expr over sibling field names
    "readOnly": true
  }
}
// dependent options: this Select's options come from a resource, filtered by another field
"interaction": {
  "optionsFrom": { "source": "products", "value": "id", "label": "name",
                   "filter": { "categoryId": "{{categoryId}}" } },  // re-fetch when categoryId changes
  "dependsOn": ["categoryId"]
}
// onChange side-effect: when this field changes, fetch + set another field/options
"interaction": {
  "onChange": { "fetch": { "resource": "customers", "by": "id", "from": "customerId" },
                "set": { "address": "{{result.address}}" } }
}
```
A small, safe **function library** available to formulas: `daysBetween`, `hoursBetween`, `sum`, `min`, `max`, `round`, `if`, plus `+ - * /`. No arbitrary JS.

## Slices

### S1 — Reactive form controller (renderer) — the runtime
`packages/renderer` (or `packages/library` Form): a controller that, on any field change:
1. builds the current field-value map;
2. **topologically evaluates** all `computed` fields (dependency graph from formula variable refs; cycle-guard) via the expression engine + function library; writes derived values (read-only inputs);
3. for fields with `dependsOn`/dynamic `optionsFrom.filter`, **re-fetches** options when a dependency changes (debounced), against `/api/data/<source>?<filter>`;
4. runs `onChange.fetch`→`set` side-effects.
Derived/dependent fields render disabled-but-visible with the live value. Reuse `interpolate`/`evalExpression`; add the function library. Tests: formula recompute on input change, dependency cycle guard, dependent-select refetch, onChange populate.

### S2 — Deterministic auto-derivation (generator) — seed the obvious cases
`backend/services` form builder pass: from the registry + column names, emit interaction blocks for high-confidence cases:
- a numeric field named `total|amount|cost|subtotal` with sibling `qty|quantity|rate|price|unitPrice` (and optionally date range) → a `computed.formula`;
- a Select whose entity has a FK to the entity of another Select on the form → `dependsOn` + filtered `optionsFrom` (e.g. product depends on category);
Conservative: only emit when the pattern is unambiguous; everything else is left for the editor. Validated by the binding gate (formula vars + optionsFrom.source must resolve to real fields/resources). Tests: rental(rate,start,end)→total computed; product/category dependent select.

### S3 — Editor authoring UI (frontend) — user manages interactions
`frontend/` form-field editor panel: per selected field, a UI to define
- **Computed**: a formula builder (insert sibling field refs + operators + functions) → writes `interaction.computed`;
- **Depends on / options from**: pick a source resource + value/label + a filter keyed on another field → writes `interaction.optionsFrom` + `dependsOn`;
- **On change**: pick a fetch resource + which result fields set which target fields.
Round-trips through the same schema the renderer reads (single source of truth). Live preview in the canvas.

## Reuse / non-invention
- Expression eval: existing feel-lite `evalExpression` (`packages/renderer/src/runtime/bindings.ts`) + a whitelisted function library. NO new language, NO `eval`.
- Data fetch: existing `/api/data/[...path]` + loader; dependent selects reuse `optionsFrom` resolution already in the renderer.
- Binding gate (strict) validates formula variables resolve to real sibling fields and `optionsFrom.source` to a real resource.

## Out of scope (for now)
- Cross-page/global state; multi-step wizards; server-side computed validation (client-computed value is still re-derivable server-side later).

## Scope decisions (locked with user, 2026-07-14)
1. **Build all three slices together** (S1 runtime + S2 auto-derivation + S3 editor authoring) — users both receive interactive forms AND fully manage interactions from the editor.
2. **Aggressive auto-derivation** — infer computed totals and dependent dropdowns from looser signals (any numeric field near price/date fields; any two related entities), accepting that some guesses will be wrong and are correctable in the editor. Because guesses can be wrong, S3 (editor) must make every auto-derived interaction visible + editable + removable, and the strict binding gate must still validate formula vars + optionsFrom.source resolve (a wrong-but-resolvable formula is a UX issue the editor fixes, not a build failure).

## Execution note
Large multi-surface feature (renderer + backend + frontend editor) — gets its own TDD plan (docs/superpowers/plans/) and subagent execution, sequenced S1 (runtime, the foundation everything renders through) → S2 (generator auto-derive) → S3 (editor), with the field-interaction contract shape frozen first so all three read one schema.
