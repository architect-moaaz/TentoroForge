# Read-Binding Contract — Spec

## Problem
Generated pages ship data-bound nodes — Tables, Charts, maps (ResourceTimeline/Calendar/Timeline/Kanban), and Stat tiles — whose binding key `{{name}}` points at a dataSource that does not exist on the page. At runtime the renderer returns the **literal `"{{name}}"` string** for an unknown source (`packages/renderer/src/runtime/interpolate.ts:57-66`), so the node receives a string where it expects an array/number and renders empty **with no error at build or runtime**. This is the read-side twin of the button→workflow mismatch we already cured on the write side (action-contract + binding gate). Two live symptoms: `{{drives}}` orphaned by a dataSource rename (naming drift), and `{{activeRecruitmentDrives}}` / `{{recentApplicants}}` / `{{upcomingInterviews}}` — **derived widgets whose filtered dataSource was never declared**.

## Principle (agreed with user)
Every read-bound node must be **authored against the real registered resources and validated before ship**, exactly like buttons. The LLM keeps judgment (which entity a widget shows, page composition); the system guarantees the exact, resolvable reference. Decision on derived widgets: **materialize** the missing dataSource (decode the semantic prefix into a filter/sort/limit over the real entity) rather than renaming onto the base list (which caused name collisions).

## The two failure classes
- **Class A — naming drift**: a real dataSource exists; the binding key just doesn't match (`{{drives}}` ↔ `recruitmentDrives`). Already closed at gen-time for `rows`/`items` by the final `reconcile_list_sources` pass (commit `7c87e27`). This spec extends that heal to the uncovered binding props.
- **Class B — phantom/derived widget**: the widget wants a filtered/limited view (`active`, `recent`, `upcoming`, `open`, `pending`, `top`) that **no dataSource declares**. Fix = materialize the dataSource.

## Registries (source of truth — reuse existing readers)
- Entities/slugs + columns + types + FKs + enum/status columns: `src/db/schema/*.ts` via `binding_validator`'s readers (`_read_schema_tables`, `_SlugResolver`, `resource_registry_context._read_entities`). Do NOT reinvent canonicalization.
- Page dataSources: the page-level `dataSources[]` array (name/entity/op/filter/sort/limit; ops `list`/`aggregate`/`series`/`get`).

## The complete read-binding surface (from code map)
| Node type | Binding prop(s) | Value form | Materialize op |
|---|---|---|---|
| Table / DataTable / DataGrid | `rows` | `"{{name}}"` | `list` |
| List / DataList / CardList / RecordList / ListView | `items` (also `data`,`records`) | `"{{name}}"` | `list` |
| Chart | `data` | `"{{name}}"` | `series` |
| ResourceTimeline | `resources` **and** `items` | two `"{{name}}"` | `list` |
| Calendar | `events` | `"{{name}}"` | `list` |
| Timeline | `entries` | `"{{name}}"` | `list` |
| Kanban | `data` | `"{{name}}"` | `list` |
| Stat / MetricTile / KPI / Gauge / Progress / Counter / Scorecard | `value` (also `current`,`count`,`score`) | `"{{name.metricKey}}"` (dotted) | `aggregate` |

Non-bindings to leave alone: Chart `series` prop (`[{name,dataKey}]` config), `optionsFrom.source` (bare string, write-side/Select — already validated).

## Target architecture (3 slices, mirrors the button contract)

### Slice R1 — the materialize reconciler (deterministic core)
New module `backend/services/read_binding_guard.py::reconcile_read_bindings(output_dir) -> dict`. Idempotent, own try/except, loud logging, byte-stable. Runs as the **final read-binding pass**, after `schema_references` (so it heals rename orphans) — it supersedes and absorbs the second `reconcile_list_sources` re-run for the broadened key set (keep the old call for now; the new guard is additive and idempotent).

Algorithm, per read node with a single-token `{{X}}` (or dotted `{{X.field}}` for stats) in any binding prop above:
1. **Resolved** — `X` (root of dotted) is a declared dataSource `name` on the page → OK, record `resolved`.
2. **Rename (Class A)** — unique canonical match among the page's dataSource names of the compatible op → rewrite `{{X}}`→`{{match}}`, record `remapped`.
3. **Materialize (Class B)** — decode `X`:
   - **Base entity**: strip a known semantic prefix (`active|open|recent|latest|upcoming|pending|new|top|closed|completed`) and any trailing view suffix; canonical-match the remainder to a **registered entity slug**. If no real slug → **do not guess**; leave dangling → `unresolved` (validator will error).
   - **op** by node type (Chart→`series`, Stat→`aggregate`, else `list`).
   - **filter/sort/limit** from the prefix, using the entity's REAL columns (reuse the enum/status + date-field readers):
     - `active|open` → `filter` on the entity's status-like column to its "active/open" enum value (only if such a column+value exists; else omit filter).
     - `pending` / `completed` / `closed` → same status mapping to the matching value.
     - `recent|latest|new` → `sort:{field:<createdAt-like>,direction:"desc"}` + `limit:5`.
     - `upcoming` → on a future-date column: `sort` asc + `limit:5` (filter to `>= now` only if the runtime supports it; otherwise sort+limit alone).
     - `top` → `sort` desc + `limit:5`.
   - Append a new dataSource `{name:X, entity:<Entity>, op, ...filter/sort/limit}` to the page (dedup by name), leave the binding `{{X}}` as-is (now resolvable). Record `materialized`.
   - For **Chart** materialize, also normalize the render config the way `chart_data_source_guard` does (`data="{{X}}"`, `xKey/label`, `series=[{name,dataKey:"value"}]`) so a series source renders.
   - For **Stat** dotted `{{X.metric}}`, materialize an `aggregate` dataSource with a single metric keyed by the dotted field (`fn:count`, plus prefix-derived filter), so `{{X.metric}}` resolves.
4. Write `<output_dir>/contracts/data-contract.json` (mirror `action-contract.json`): `{version:1, nodes:[{file, node_type, binding_prop, binding_name, entity, op, resolved:bool, action:"resolved|remapped|materialized|unresolved"}]}`. Deterministic/sorted.

Reuse `chart_data_source_guard` / `widget_data_source_guard` helpers for the actual dataSource-object construction where possible — do not duplicate series/aggregate shaping.

### Slice R2 — author against the registries (page-agent instruction)
Extend `resource_registry_context.build_resource_context` so the "Closed resource set" rules cover **every** read widget, not just Table-rows: instruct the model that each Table/List/Chart/map/Stat MUST declare a page dataSource over a listed entity and bind its data prop (`rows`/`items`/`data`/`resources`/`events`/`entries`/`value`) to that dataSource by exact name; for a filtered view (active/recent/etc.) it must declare the dataSource **with** the filter/sort, not invent a bare binding name. Lowers the rate the reconciler must repair.

### Slice R3 — validate & FAIL (extend the gate)
Extend `binding_validator._check_page`:
- Broaden the read-binding-key set from `("rows","items")` to include `data`, `resources`, `events`, `entries`, and dotted Stat `value`/`current`/`count`/`score` (root-of-dotted must be a dataSource name).
- Each unresolved read binding stays an **error** (`binding_unresolved`) — so under `FORGE_BINDING_GATE=strict` a page with any dangling table/chart/map/stat binding fails generation, the same bar buttons already clear. Default/warn unchanged.

## Wiring
`backend/services/post_generate_fixes.py`: add `read_binding_guard.reconcile_read_bindings(output_dir)` as the final read-binding pass (after `schema_references` at line 527 and after the existing final `reconcile_list_sources` at line 552), in its own try/except with a summary log. No behavior change when there is nothing to heal.

## Tests (TDD)
Unit (`backend/tests/test_read_binding_guard.py`):
- Class A: Table `rows:{{drives}}` + dataSource `recruitmentDrives` → remapped to `{{recruitmentDrives}}`.
- Class B list: Table `rows:{{activeRecruitmentDrives}}`, entity `RecruitmentDrive` with a `status` enum incl. `Active` → materializes `{name:activeRecruitmentDrives, entity:RecruitmentDrive, op:list, filter:{status:Active}}`; binding now resolves.
- Class B recent: List `items:{{recentApplicants}}` → materializes `op:list, sort:{createdAt,desc}, limit:5`.
- Class B chart: Chart `data:{{applicantsByStatus}}` dangling → materializes `op:series, groupBy:status`; sets `xKey`/`series`.
- Class B stat: Stat `value:{{openDrives.count}}` → materializes `op:aggregate` metric `count` (filter open) so dotted binding resolves.
- Map: ResourceTimeline `resources:{{technicians}}` + `items:{{workOrders}}` dangling → both materialized `op:list`.
- No real entity for the stripped base → left `unresolved`, recorded, not guessed.
- Idempotent: second run is a no-op (byte-identical).
- `data-contract.json` written, deterministic, sorted.
- Validator (`test_binding_validator.py`): a dangling Chart `data`/`resources`/`events`/dotted `value` now produces an `error` (previously missed); an all-materialized page → `ok:True`.
- resource_registry_context: emitted context mentions Chart/List/map/Stat binding rules (not only Table-rows).

## Out of scope
- Runtime `>= now` date filtering if the data engine lacks operator support — fall back to sort+limit (note in code).
- New chart/map components; renderer changes (the literal-string behavior is the *signal* the gate consumes, not a bug to fix here).
- Write-side (buttons/forms/optionsFrom) — already covered.
