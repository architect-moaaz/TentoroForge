# Widget anatomy + composition recipes

**Status**: spec, not implemented.
**Owner**: dashboard/collection/record composer workstream.
**Companions**:
- `2026-08-11-intelligent-rich-forge.md` — the substrate this sits on
- `2026-08-12-pipeline-cleanup.md` — dashboard/collection/record authority (already landed as P3/P6)

Cure for the "every generated app looks the same" class. The paint
layer is genuinely varied today (visual-lock, palette, fonts, radius,
skin all diverge across recent apps). What's cloned is the
**compositional grammar**: every dashboard is `Stack{Hero, KPI-row,
Recent-Table}`; every list is `Heading + New button + Table`; every
detail is `Heading + DescriptionList`. Different colors, identical
shapes.

Two reference points frame the target:

- **Bank of America suite** (Demographics / Financial Health /
  Transactions) — one product template with three genuinely different
  dashboards. Same weight-split display header, same left-KPI-stack +
  right-hero-chart split, but each dashboard tells a different story
  because its **KPI anatomy** and **chart choices** are wired for the
  data. KPIs have breakdowns (`Clients 2,000 / Male 984 / Female
  1,016`, `Total Debt $127M / Max $516K / Min $5`). Charts have
  semantic color consistency (pink = female, green = pass,
  red = risk). One chart is bar + line overlaid on the same axes.
  Another is a ranked horizontal-bar leaderboard.
- **DORA Metrics** — a completely different species. No KPIs, no
  hero. Just a 2×2 chart grid with filter chips at top. Engineering
  audiences read patterns from many small time-series, not
  headlines.

Two observations:

1. **Same archetype (`dashboard`) can host radically different
   compositions.** The Banking suite and DORA are both "dashboards"
   but their compositional grammars share nothing.
2. **Within a widget, anatomy matters more than novelty.** A stat
   card with number + breakdown + min/max tells a story a bare
   `{value, label}` card cannot, without adding any new component
   types.

The pipeline supports variance at the wrong layer (shell) and misses
it at the two layers that matter (**composition of the content
region**, **anatomy inside the widget**).

---

## Problem

Three concrete gaps, each with a canonical failure mode.

### Gap 1 — widget anatomy is minimal

`KPI` (`Stat` component) today accepts `{title, value, format,
delta?}`. That produces `Queued Batches / 0`. The Banking KPIs are
richer: `Clients / 2,000 / Male 984 / Female 1,016`. That extra
breakdown is not an accident — it's the reason the number is legible
(2,000 means little without the split).

Same story for `Chart`. Today: single series, one encoding (bar OR
line OR donut). The Banking "Transactions Yearly" chart is bar +
line on the same axes — Transaction Amount as bars, Total
Transactions as a smoothed line overlay. Distinct visual grammar,
not a novel component.

Canonical failure: the Banking Archive KPIs render as `Queued
Batches / 0`, `Processing / 0`, `Complete Today / 0`, `Failed /
Partial / 0`. Four zeros in a row. Even with real data the shape
would be four bare integers — no breakdown, no threshold color, no
delta.

### Gap 2 — composition is one recipe

Every dashboard/collection/record composer emits
`root: Stack{gap, children: [...vertical sections]}` (verified across
three composers in the last audit). The LLM path enforces this
literally in the prompt: *"The root node MUST be a Stack"*. `SplitView`,
`Sidebar`, `InspectorPanel`, `Grid`, `Cluster` ship in the library
with zero call sites at the page root.

Which means: even if the dashboard maquette contract were widened to
express "asymmetric split with KPI stack on the left and hero chart
on the right" (Banking's signature), the composer would flatten it to
a top-down Stack because that's the only root primitive it knows how
to emit.

Canonical failure: the Banking suite's Demographics dashboard has a
1/3 KPI-stack + 2/3 hero-chart split above a 4-column small-multiples
row. Forge would compose the same content as a top-down Stack: KPIs
first, then chart, then more charts stacked below. Same widgets,
completely different reading experience.

### Gap 3 — section chrome is bare

Real dashboards ship with a **subtitle** ("Evaluating Our Current
Clients Demographics"), a **filter bar** (dropdowns or chips), and a
**reset-all-filters** control at the top-right. Forge dashboards
today ship with just the H1 title.

Canonical failure: three dashboards in a suite must feel *related but
different*. Without the filter chrome and subtitle, they read as
`Heading + KPIs + Table` × 3 — indistinguishable at a glance.

---

## Non-goals

- Not adding new widget component types. `Stat`, `Chart`, `Table`,
  `Kanban`, `Calendar` etc. already exist in the library. Anatomy
  work extends their props, doesn't invent new primitives.
- Not adding new page types beyond what the planner-type-vocabulary
  work (separate spec) does. Composition recipes attach to existing
  `type: dashboard | list | detail`.
- Not changing the shell picker or design-language layers. Those
  work; this fills the gap they leave behind.
- Not landing a self-verify loop or a new guard. This spec follows
  the authority principle: extend the plan/maquette contract with new
  fields, composers dispatch on them, no fallback classifier and no
  env gate.

---

## Design principles

**Authority over guards.** Every decision in this spec is a positive
value the plan or maquette declares. Missing = the safe default
(`kpi-hero-split` recipe, no breakdown, no filter bar). No route
fallback, no env flag, no "if unclear then Stack".

**Anatomy travels with the widget.** A KPI's breakdown, delta,
threshold live on the KPI's own maquette node — not in a sibling
"annotations" section, not derived post-hoc. The composer reads the
node and emits props. One-to-one.

**Recipes are pure dispatch.** `select_composition(page.type,
archetype, brief) → recipe_name` is a lookup table. The recipe
declares a root primitive (`SplitView`, `Grid`, `Stack`) and where
each maquette section (`kpis`, `hero_chart`, `small_multiples`)
plugs in. No conditional logic in composers.

**Extensible without touching composers.** Adding a 6th recipe or a
7th KPI anatomy variant is a new entry in a registry, not a code
change to the composer branch.

---

## Slice A — widget anatomy contract

Extends the LLM-authored maquette schemas (`DashboardMaquette`,
`CollectionMaquette`, `RecordMaquette`) with anatomy fields. Every
new field is optional — omission means "use the current bare
rendering", so the change is byte-safe for existing plans.

### KPI anatomy

Today's KPI slot in the dashboard maquette:

```json
{"kind": "stat", "title": "Total Debt", "value_ref": {"metric": "sum", "column": "debt"}}
```

New fields:

```json
{
  "kind":        "stat",
  "title":       "Total Debt",
  "value_ref":   {"metric": "sum", "column": "debt"},

  "format":      "currency" | "number" | "percent" | "duration",
  "delta":       {"period": "prev_month", "positive_is_good": false},
  "threshold":   {"warn_above": 100, "critical_above": 150, "color_on_value": true},
  "breakdown":   [
    {"label": "Male",   "value_ref": {"metric": "count", "filter": {"gender": "M"}}},
    {"label": "Female", "value_ref": {"metric": "count", "filter": {"gender": "F"}}}
  ],
  "extremes":    {"max_label": "Single Max Debt", "min_label": "Single Min Debt"}
}
```

Which the composer emits as:

```
[Stat]
  Total Debt
  $127,419,388                    ← primary value (colored red if > threshold)
  ▲ 12.3% vs last month           ← delta chip
  ──
  Male    984                     ← breakdown lines
  Female  1,016
  Single Max Debt  $516K          ← extremes
  Single Min Debt  $5
```

`Stat` component props extend to accept `breakdown[]`, `extremes`,
`delta`, `threshold`. Zero of these are required; a bare Stat with
just value + label renders exactly as today.

### Chart anatomy

Today's chart slot:

```json
{"kind": "chart", "chartType": "bar", "title": "Transactions", "series": [{...}]}
```

New fields:

```json
{
  "kind":         "chart",
  "chartType":    "bar",
  "title":        "Transactions Yearly and Time Trend",
  "series":       [{"label": "Transaction Amount", "value_ref": {...}}],

  "overlay":      {"chartType": "line",
                   "series":    [{"label": "Total Transactions", "value_ref": {...}}],
                   "curve":     "smooth"},
  "view_toggles": [
    {"label": "Time Trend", "modifier": {"series_field": "month"}},
    {"label": "Year Trend", "modifier": {"series_field": "year"}, "default": true}
  ],
  "encoding":     {"stacked": false, "sorted": "desc", "top_n": 10,
                   "value_labels": true, "leaderboard": true},
  "semantic_color": {"by": "field", "field": "gender",
                     "map": {"M": "var(--male)", "F": "var(--female)"}},
  "help":         "Debt-to-Income above 40% is flagged risky"
}
```

- `overlay` lets one chart carry two encodings on shared axes (bar + line).
- `view_toggles` renders pill-buttons in the chart header that swap the
  series modifier at runtime.
- `encoding.leaderboard` renders as a ranked horizontal bar with value
  annotations at the row end (the Banking "Transactions Across
  Merchant State" shape).
- `semantic_color.by = "field"` binds a data field to color
  consistently across all charts in the dashboard (pink = female
  everywhere).

### Table anatomy

One incremental field — enough to lift Tables from generic:

```json
{
  "kind":       "table",
  ...
  "row_action": {"kind": "navigate", "route": "/batches/{id}"},
  "row_status": {"field": "status", "as": "left_stripe"},
  "empty":      {"illustration": "empty-inbox", "title": "No batches yet",
                 "action": {"label": "Upload batch", "route": "/upload"}}
}
```

Not novel — `row_action` and `empty` are things the existing Table
supports as ad-hoc props. Formalizing them in the maquette contract
makes them consistent instead of LLM-guessed per page.

---

## Slice B — composition recipes

New module `services/composition_recipes.py`. Pure registry, no
side-effects, no LLM. Registry entry looks like:

```python
Recipe(
    name        = "asymmetric-split",
    root        = Primitive.SPLIT_VIEW,
    slot_map    = {
        "primary":   ["kpis"],           # left side ~1/3
        "secondary": ["hero_chart"],     # right side ~2/3
        "footer":    ["small_multiples"],
    },
    hints       = {"ratio": "1fr 2fr", "gap": "tokens.spacing.6"},
)
```

Initial recipe catalog:

| Recipe | Root primitive | Slot map | When it fits |
|---|---|---|---|
| `kpi-hero-split` **(default)** | Stack | header → KPI grid → hero chart → activity | The safe universal. Today's behavior. |
| `asymmetric-split` | SplitView | left(kpis, dense stack) + right(hero_chart) → small_multiples | Data-rich analytical dashboards — Banking Demographics/Financial Health template. |
| `chart-grid` | Grid | filter_bar → grid(chart × 4-6) | Engineering/ops dashboards — DORA-style. No KPIs, no hero. |
| `ranked-leaderboard` | Split | left(leaderboard chart) + right(detail card) | "Top-N X" screens where selecting a row reveals detail. |
| `command-center` | Grid | header row + main(large chart) + right rail(status widgets) | High-density operational — trading desk, NOC, dispatch. |
| `inspector-panel` | SplitView | main(list/kanban) + right(inspector for selection) | Case-management, ticket triage. |

Selection is deterministic — a **lookup**, not an LLM:

```python
def select_composition(page_type: str, archetype: str, brief: dict) -> str:
    # 1) Vocabulary declares a recipe → use it (highest authority)
    vocab = load_vocabulary(archetype)
    if vocab and vocab.dashboard_recipe:
        return vocab.dashboard_recipe

    # 2) Page-type + register heuristics (small, transparent)
    if page_type == "dashboard" and brief.get("register") in ("analytical", "quant-heavy"):
        return "asymmetric-split"
    if page_type == "dashboard" and archetype in ("dev-tools", "observability", "monitoring"):
        return "chart-grid"
    if page_type == "list" and brief.get("interaction_model") == "triage":
        return "inspector-panel"

    # 3) Safe default
    return "kpi-hero-split"
```

Vocabularies grow a `dashboard_recipe: str` field (companion to the
existing `primary_screens_per_persona`) so domain-authored
recipes win over the heuristic. Example:

- `banking-platform` → `asymmetric-split` (Banking Demographics vibe)
- `dev-tools` → `chart-grid` (DORA vibe)
- `crm` / `case-management` → `inspector-panel`
- `booking-platform` → `kpi-hero-split` (default is fine; the shape
  variance for booking comes from `type: "calendar"`, a separate
  spec)

---

## Slice C — section chrome

Three new fields at the top of every dashboard/collection maquette:

```json
{
  "subtitle":  "Evaluating Our Current Clients Demographics",
  "filters":   [
    {"kind": "select",     "field": "loan_risk",    "label": "Select Loan Risk"},
    {"kind": "select",     "field": "debt_category","label": "Select Debt Category"},
    {"kind": "date-range", "field": "created_at",   "label": "Date range"}
  ],
  "reset_filters": true,
  "sections": [ ... existing kpis / hero_chart / small_multiples ]
}
```

Composer emits:

```
[Header block]
  Demographics Dashboard              [ i ]  [ ↺ Reset all filters ]
  Evaluating Our Current Clients Demographics

[Filter bar]  (only when filters[] non-empty)
  Loan Risk ▾   Debt Category ▾   Date range ▾

[Sections]
  ... (composed via the chosen recipe)
```

Section chrome runs *before* the recipe dispatch — it's the same for
every recipe. `filters` state syncs to URL query params so the
"reset" action is a single `router.push(pathname)`. All filters
narrow the `dataSource` bound to every widget below (widgets
already accept `filters` at the data-engine level; this wires the
control surface).

`subtitle` and `filters` fall out of the same brief the planner
already has (`register`, `dominant_verbs`, `key_dimensions`) —
low LLM lift, high visual return.

---

## Rollout order

Independent slices, but ordered by ROI:

1. **Slice C (chrome)** — 1 day. Immediate visible variance across
   every dashboard, no risk to shape. Subtitle + filter bar +
   reset button is a Banking-vs-DORA-vs-generic-Forge tell at
   first glance.
2. **Slice A KPI anatomy** — 2 days. Extends the Stat component
   props, extends the maquette schema, extends the LLM prompt with
   one paragraph of guidance ("declare breakdowns when the value's
   composition matters"). Live-verify on Banking Archive: `Queued
   Batches / 0` becomes `Queued / 0 / Awaiting OCR 0 / Manual review 0`
   or similar.
3. **Slice A Chart anatomy** — 2 days. Overlay + leaderboard modes
   in the Chart component. `view_toggles` deferred to a fast-follow.
4. **Slice B (recipes)** — 3 days. New module, new dispatch, wire
   into all three composers (dashboard/collection/record). Requires
   loosening the "root MUST be Stack" prompt constraint and the
   validator to accept `SplitView`/`Grid` at page root.

Whole thing: ~1.5 weeks, 4 sub-slices, each independently mergeable
and each visibly improving the next generation.

## Acceptance

Regeneration of the Banking Archive prompt (`vpvu0m2y` was the
baseline) should produce a `/` landing that has:

- **Subtitle** ("Evaluating batch processing across archivists and
  compliance officers" or similar)
- **Filter bar** with at least Date range + Status
- **Asymmetric split** — KPI stack on the left, "Batches by Status"
  hero chart on the right
- **KPIs with breakdown** — `Queued / N / Awaiting OCR / Manual
  review`, not four bare zeros
- **Small-multiples row** — 4 charts along the bottom (debt by age
  group, by status, by processor…)
- **Semantic color** — status colors (green/amber/red) consistent
  across every chart

None of that requires changing what the Banking Archive is *for*.
It's the same content, in a composition and anatomy that finally
tells the story.

Regeneration of a "monitoring" or "dev-tools" prompt should produce
a `/` landing that's a **chart-grid** — 2×2 or 3×3 charts with
filter chips at top, no KPIs, no hero. Different recipe, same
content model.

Two apps in the same archetype should still share the *recipe* (so
Demographics and Financial Health both use asymmetric-split, feeling
like siblings) but differ in KPIs, chart choices, filter set, and
subtitle — the anatomy carries the identity.

## Risks

- **LLM authoring load.** Widening the maquette contract with 15
  optional anatomy fields could push token budgets. Mitigation: the
  planner already handles ~32K-token plans; the anatomy additions
  are ~1-2K per dashboard. Well within budget.
- **Component prop explosion.** Stat's props go from ~4 to ~10. Kept
  under control by everything being optional with sensible defaults;
  none of the current usage sites need to change.
- **Recipe count creep.** 6 recipes is a good starting point — if
  every domain wants a bespoke recipe, that's a signal we should
  reify the domain distinction (vocabulary), not add more recipes.
  Discipline: a new recipe needs a real reason two existing recipes
  can't accommodate the shape.
