# Tentoro Forge — Pipeline Reliability Atlas & Remediation Plan

Source: a 7-slice parallel audit of the whole generation pipeline + generated-app runtime (2026-07-14). Each slice inventoried its corner against one lens: *what authority should it read → does it read or re-derive/override → ordering hazards → failure modes → prevented / reconciled / unguarded.*

## The answer to "why do the deterministic developers override or miss the instructions"

The platform generates authority (plan → contracts → registries) but treats it as **output, not input**. Four systemic faults, each confirmed with file:line evidence:

- **F1 — Authority not enforced as input.** Artifacts are written, then downstream generators re-derive from the raw concept and agree only by luck; and the two registries have *diverged* from each other and from the real schema.
- **F2 — Ordering hazards.** Generators snapshot state before a later pass mutates it; templates clobber each other; guards re-break each other's work.
- **F3 — Unconstrained LLM authorship.** An entire plan-ingestion path skips all normalization; the page/schema agents can emit names/bindings/columns absent from the closed set.
- **F4 — Reconciliation over prevention + zero end-to-end verification.** A 36-guard patch layer catches *seen* shapes; four runtime swallow-layers turn every unseen defect into silent empty UI; nothing builds or runs the app before shipping.

---

## Failure-mode atlas (severity-ranked, grouped by fault)

### F1 · Authority not enforced / registries diverged
| ID | Finding | Where | State |
|---|---|---|---|
| A1 | **Duplicate schema files (`customer.ts`+`customers.ts`).** The LLM-skip gate `_schema_files_complete` checks the file via hint-*blind* `to_slug`, but `build_schema_files` writes it under the hint-*aware* registry slug → gate misfires → LLM schema agent re-emits the *other* plural over a complete build. `schema_dedup_guard` can't catch (different pgTable keys). **Root of `unknown table` AND the data-init build break.** | generate.py:255,276; schema_agent.py; schema_dedup_guard.py:139 | UNGUARDED |
| A2 | **Two registries diverge.** `resource-registry.json` is built from the raw plan and never reconciled to the real schema → stale `notNull`/absent `enum`. `registry.json` *is* reconciled (`reconcile_entities`). Page agent reads the stale one; form guards read the correct one → inconsistent forms. | resource_registry.py:135,68; generate.py:898; resource_registry_context.py:104 | UNGUARDED |
| A3 | **Access model never enters either registry.** `access_control`/`field_access`/workflow roles dropped; `resource_registry` hardcodes `roles:[]`. RBAC enforcement would have no authority to read. | planner.py:575,723; resource_registry.py:210 | UNGUARDED |
| A4 | **UI-intent dropped on the deterministic path.** `api_strategy.workflow_actions` (`visible_when`/`ui_location`/`on_success`) consumed only by the LLM contract agent, which is skipped when deterministic contracts pass. | contract_generator.py:446; generate.py:833 | UNGUARDED |
| A5 | **3–4 independent name derivers** (registry-based `build_schema_files`; re-deriving LLM `schema_agent`; snake-plural `crud_workflow_generator._derive_table`; raw planner `config.table` literals). Agree by luck. | schema_builder.py; schema_agent.py:301; crud_workflow_generator.py:86; planner.py:563 | partially reconciled |
| A6 | `enum_values` never emitted at plan time; canonical registry never backfills → canonical enums always null. | planner.py:496; resource_registry.py:68 | UNGUARDED |

### F2 · Ordering hazards / clobber / guard-vs-guard
| ID | Finding | Where | State |
|---|---|---|---|
| O1 | **Template dep divergence (P0 build break).** `app-foundation` floor imports `@radix-ui/*`, `@tanstack/react-query`, `recharts`; `standalone-app` `package.json.tmpl` (which clobbers) lists none → guaranteed `Module not found`. | app_emitter.py; standalone-app/package.json.tmpl; foundation providers.tsx/ui/* | UNGUARDED |
| O2 | **emit clobbers inject's dep patch.** `inject_runtime._ensure_package_deps` adds deps, then `emit_standalone_app` rewrites package.json wholesale. | generate.py:1026 then 1277; runtime_injector.py:531 | UNGUARDED |
| O3 | **next.config clobber** strips the null-loader dev-only exclusion + `@tentoroforge/editor` transpile while dev-only routes remain → `next build` breaks. | app_emitter.py:228; next_config_guard.py:79 | partially |
| O4 | **H2 guard-vs-guard: `list_data_source_guard` #2 destroys `read_binding_guard`'s materialized filters.** #2 rebinds `{{recentApplicants}}`→sole base list first; read_binding then sees it "resolved" and never builds the filtered view → "recent/active" silently unfiltered. | list_data_source_guard.py:164; read_binding_guard.py:422 | conflict |
| O5 | **H1/H3/H6** — schema_references rename → list #2 heals (double-run tax); read_binding materializes *after* the "final authority" so its sources are never canonicalized (naive inverse-pluralizer → bogus entity on `statuses`/`people`); `table_row_nav` builds `rowHref` from raw stem while the next guard rewrites routes → 404. | post_generate_fixes.py:547,572,603; table_row_nav_guard.py:67 | patched/gap |
| O6 | data-init/data-api glob schema dir **before** dedup (now guarded, but only for those 2 files; other files holding a deleted import are unreconciled). | runtime_injector.py:634; schema_import_guard.py:33 | reconciled (narrow) |

### F3 · Unconstrained LLM authorship
| ID | Finding | Where | State |
|---|---|---|---|
| L1 | **APP-BREAKING: plan-ingestion path B bypasses ALL normalization.** Interactive/figma/re-extracted plans skip `_normalize_oneshot_plan`+`_annotate_page_types`. A plan expressing entities as the `entities` dict → `create_registry` registers 0 entities → no schema → broken app. | generate.py:4653; registry.py:127 | UNGUARDED |
| L2 | **Nested-column references unguarded.** Validators check only collection/stat *root* tokens; a Table cell / DescriptionList / detail field `{{member.phoneNumber}}` naming a non-existent column → literal/empty, no error. Largest silent surface for detail pages. | binding_validator.py:374; read_binding_guard.py:58 | UNGUARDED |
| L3 | **Map/geo components unguarded** — no guard covers map markers/geojson/coordinates; a `Map` bound to `{{sites}}` renders empty. | (no code) | UNGUARDED |
| L4 | **Chunked large-page path drops page dataSources** → plain `{{entity}}` tokens unresolved on exactly the biggest pages. | chunked_schema.py:122 | UNGUARDED |
| L5 | Phantom workflow on a Form/Button is *reported*, only CRUD-verb names auto-heal; a genuinely invented name stays dangling → dead button (gate warns, ships). | action_contract_guard.py:296; self_heal.py | reconciled-partial |

### F4 · Reconciliation over prevention / no end-to-end check / silent degradation
| ID | Finding | Where | State |
|---|---|---|---|
| V1 | **Empty DB.** Seeder reads rows from a `seed_data` dict no generator populates; never consumes `row_count`; per-row failures swallowed; the realistic-row generator is unconditionally skipped because the template seed already exists → `users\|1`, all domain tables 0. | seed.ts:225,232; seed_generator.py:109; contract_generator.py:589 | UNGUARDED |
| V2 | **Gates are off/advisory.** Binding gate fails only under `FORGE_BINDING_GATE=strict` (default warn); seed-smoke off-by-default + marker-based (never compares realized counts to `row_count`). | generate.py:428; seed_smoke.py:32 | advisory |
| V3 | **Four runtime swallow-layers** (`data-engine`→`data-engine-bridge`→`loader`→`schema-page`) convert wrong entity/column/slug into indistinguishable empty UI; **literal `{{expr}}` leaks** to users when a source silently resolves empty. | data-engine.ts; interpolate.ts:66; bindings.ts:75 | masks bugs |
| V4 | **SSR/API registration asymmetry.** SSR registers entities from a hard-coded list in `data-init.ts`; the API route registers dynamically → same entity unknown server-side but fine client-side → intermittent-looking empty. | data-init.ts; data-api-route.ts | UNGUARDED |
| V5 | Workflow runtime silently drops unresolved value-map fields, skips unknown action types (reports `completed`), `lookupByRole` is a `null` stub → partial writes / no-op steps with no signal. | workflows/index.ts:365; engine.ts:476,512 | UNGUARDED |
| V6 | **Dead config-repair code** (`_fix_tailwind_config`, `_fix_common_agent_mistakes`, `pg`→`postgres`) has no production caller → clobbered postcss/tailwind/db config has no backstop. | runtime_injector.py:1394,1293 | dead |
| V7 | Vendoring silent-skips a missing package / ships stale dist on build failure → broken `file:` deps. | app_emitter.py:71,89 | UNGUARDED |

---

## Remediation plan (architectural, not more guards)

**Principle:** the registry becomes a *true contract* — generated once, **reconciled to ground truth**, **enforced as the sole input**, and **verified end-to-end** — collapsing the guard layer instead of extending it.

### P0 — stop the bleeding (ship-blocking: build breaks, empty DB, broken apps)
1. **Template dependency unification** (O1/O2/O3). Make `standalone-app/package.json.tmpl` a superset of everything the `app-foundation` floor imports (radix, react-query, recharts), OR stop the clobber and merge deps. Add a deterministic check: every `@/…`/bare import in the emitted app resolves to a dep or file. *(fixes the P0 `Module not found` class)*
2. **Schema skip-gate fix** (A1). `_schema_files_complete` consults the registry slug (`name_family`/`_reg_slug`), so the gate looks for the file the deterministic writer actually wrote → the LLM schema agent never runs over a complete build → duplicate-file class dies at the source.
3. **Real seed generator** (V1). Synthesize N rows/entity from schema+registry (valid types, FKs in dependency order, enum-valid), insert, and **fail loud** on "0 rows where N planned"; retire the rows-from-empty-dict design.
4. **Universal plan normalization** (L1). Call `_normalize_oneshot_plan`+`_annotate_page_types` at the generation entrypoint for *every* plan path (interactive/figma/re-extracted), not inside one planner variant.

### P1 — authority as an enforced contract
5. **One reconciled registry** (A2/A5/A6). Merge `resource-registry.json` + `registry.json`; after schema generation, reconcile the registry against the real schema (ground-truth `notNull`/enum/types); build it once and **thread the single object** to every consumer. Kills the divergence and the "built 2–3×" waste.
6. **Registry owns the access model** (A3) and **UI-interaction intent** (A4) — so RBAC and `visible_when`/`on_success` have authority and the deterministic path stops dropping them.
7. **Build gate** — run `next build` as a hard acceptance step. This is the mechanism that catches the *unknowns* (template dep gaps, config clobber, module-not-found, hallucinated imports) that guards can't enumerate.
8. **Behavioral + seed gate on by default** — assert rows landed and dispatch each workflow with a synthesized payload asserting a DB effect; make `FORGE_BINDING_GATE=strict` and the seed/behavioral gates the default, not opt-in.

### P1.5 — collapse the guard layer (enabled by 5)
9. Retire the now-dead reconcilers (`workflow_table_guard`, `list_data_source_guard` ×2, `nav_route_reconcile_guard`, `schema_import_guard`, `schema_dedup_guard`, `repair_fk_dropdowns`); collapse `schema_references` to a pure validator; fix **O4/H2** (order read-binding materialize before the base-list collapse, or merge them).

### P2 — hardening / close silent surfaces
10. Extend binding validation to **nested column refs** (L2), **map/geo** (L3), **chunked-page dataSources** (L4).
11. Revive or delete the **dead config-repair** functions (V6); make **vendoring fail loud** (V7).
12. Reduce the **runtime swallow-layers** to a single diagnostic boundary (V3/V4/V5) — a dev-mode surface that reports "entity/column/binding unresolved" instead of rendering empty, so future defects are loud.

### Sequencing note
P0 items 1–4 are independent and each fixes a live shipping failure — do them first, in parallel. P1 item 5 (one reconciled registry) unlocks P1.5 (guard collapse) and is the spine. The **build gate (7)** is deliberately *after* the P0 template/dep fix, because turning it on before O1 would just red-fail every build on the known dep gap.
