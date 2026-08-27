# Canonical Resource Registry — Single Naming Authority — Spec

## Problem
Generated apps break at runtime because **no single component owns identity**. The plan expresses intent, but every downstream generator re-derives names independently:
- `schema_builder` names a table `equipments` (via `_to_table`), while `workflow_generator` writes `db_insert` into `equipment` → runtime **`unknown table`** (live bug, app `o67o5ubz`).
- The one-shot planner *emits* a canonical `table` per entity, but `_normalize_oneshot_plan` (planner.py:1202-1238) **drops it** — the intent is discarded.
- Interactions (button→workflow→entity, form→resource, list→dataSource) are matched across ≥4 artifacts by fragile `_canon`/singular-plural **string reconciliation**, never by a stable id.
- ≥11 modules each carry their own `_canon`/pluralizer.

We've been paying this down with reconciliation guards (`schema_references`, `workflow_table_guard`, the rename branches of the binding guards) — each a patch for drift that a single authority would make impossible.

## Principle (agreed with user)
There must be **one authority** — a Canonical Resource Registry, built **once** the moment planning finishes, that owns every entity's name family, the relationship graph, roles, and the interaction map. Every downstream generator becomes a **pure consumer** that looks up by stable id and **never re-derives a string**. The LLM planner keeps *judgment* (which entities/relationships/roles/interactions exist); the registry's deterministic normalizer owns the *strings and ids*. This extends the deterministic-contract and resource-binding work **upstream** to be the root authority, rather than a downstream reconciliation.

## The artifact: `resource-registry.json` (+ in-memory `Registry` object)
Built by a new `services/resource_registry.py::build_canonical_registry(plan) -> Registry`, persisted to `<output>/contracts/resource-registry.json`. Shape:

```json
{
  "version": 1,
  "entities": {
    "RecruitmentDrive": {
      "id": "recruitment-drive",              // stable kebab-singular id — the JOIN KEY everywhere
      "name": "RecruitmentDrive",             // PascalCase singular (display / type name)
      "singular": "recruitmentDrive",
      "table": "recruitmentDrives",           // camelCase — pgTable const + /api/data segment
      "slug": "recruitment-drives",           // kebab plural — file/route segment
      "camel": "recruitmentDrive",
      "schemaFile": "src/db/schema/recruitment-drives.ts",
      "typeFile": "src/types/recruitment-drives.ts",
      "columns": [{"name":"status","type":"varchar","notNull":false,"fk":null,"enum":["Active","Closed"]}],
      "fks": [{"column":"ownerId","targetEntityId":"user"}]
    }
  },
  "relationships": [{"from":"interview","to":"recruitment-drive","type":"many-to-one","fkColumn":"driveId"}],
  "roles": [{"id":"recruiter","name":"Recruiter","permissions":["read","write"],"ownsEntities":["applicant"]}],
  "interactions": [
    {"id":"approve-drive","sourcePage":"drives","trigger":"row_action","label":"Approve",
     "workflowId":"approve-drive","targetEntityId":"recruitment-drive","inputMap":{"status":"status"}}
  ]
}
```

**The normalizer** (the ONLY place names are assigned): promote `contract_generator._to_table/_to_slug/_to_camel` into `resource_registry.py` as the single normalizer, plus a singularizer. Per entity, compute the full name family ONCE. **Honor an explicit planner `table` hint** when present (stop discarding it): if the plan entity carries `table`, that string wins for `table`; derive the rest consistently from it. Entity `id` = kebab-singular, the stable join key used by relationships/interactions/consumers (never a display string).

## Consumers refactored to READ the registry (delete their private derivation)
| Consumer | Today | After |
|---|---|---|
| `schema_builder._emit_entity` | `_to_table(name)`, `_to_slug(name)`, local `_to_snake`, FK `_to_table(ref)` | table/slug/columns/FK-target-table **from registry** by id |
| `contract_generator` (api-client, nav-flow, seed-plan) | `_to_table`/`_to_slug` + a divergent inline kebab-singular in `_generate_navigation_flow` | all segments from registry (kills the nav-flow divergence) |
| `app_model_builder.build_app_model` | recomputes table/slug via helpers | thin **projection** of the registry (or registry supersedes app-model) |
| `workflow_generator._resolve_table` | canon-match real tables, `_to_table` fallback | registry lookup `entityId→table`; **no independent fallback** (closes equipment/equipments) |
| `resource_registry_context` (page agent) | reads real schema live | reads registry (same truth, now persisted + upstream) |
| seed generator/backstop | reads schema barrel | registry entity order + names |
| binding/table guards | private `_canon`/`_SlugResolver` | `_SlugResolver` **seeded from the registry**; rename/reconcile branches retire as drift disappears |

**The rule:** after this, **no module calls `_to_table`/`_to_slug`/`_to_camel` directly** — they call `registry.entity(id).table` etc. The normalizer lives in exactly one module.

## Pipeline wiring (both pipelines)
Insert `build_canonical_registry(plan)` in `routers/generate.py` immediately after `ensure_entity_reachability(plan)` (~line 569 relay; ~1969 figma), **before** `create_registry`, `generate_contracts` (782/2520), `build_schema_files` (837/2617), `generate_workflow_definitions` (1460), `generate_crud_workflows` (1480). Persist it; thread the `Registry` object (or reload from disk) into each consumer. `create_registry`/`registry.json` remains for field-truth + validation but is reconciled to share the registry's names.

## Phasing (green at every step — NOT a big-bang)
- **P1 — registry + normalizer, additive.** Build `resource_registry.py`, persist `resource-registry.json`, honor the planner `table` hint. Nothing consumes it yet. Full unit tests incl. the `Equipment`→(table,slug) uncountable-noun case.
- **P2 — schema_builder reads registry.** Authoritative table names now flow from the registry. Regression: existing plans produce byte-identical schema EXCEPT where they previously drifted (which is a fix).
- **P3 — workflow_generator + contract_generator + app_model_builder read registry.** This is the step that **closes the `equipment`/`equipments` class** end-to-end (schema table and workflow table are now the same string by construction).
- **P4 — page agent context + seed + guards read registry**; seed `_SlugResolver` from it; retire rename branches (keep the validator gate).
- **P5 — roles + interactions as first-class registry sections + validation.** The interaction graph resolves button→workflow→entity by id; a validator asserts every interaction/relationship references a real registry id.
- **P6 — live E2E**: regenerate an Equipment-domain app, assert schema table == workflow table, Create submit succeeds against a seeded row, no `unknown table`.

## RBAC enforcement (registry-driven) — the second half
The registry is not only the record of roles; it **drives real enforcement** in the generated app. All of it keys off the same registry ids.

**Registry additions:**
- `roles[]`: `{id, name, permissions:["read"|"write"|"delete"|"approve"], scope:"all"|"own", ownsEntities:[entityId]}`.
- Per entity: `access: {roleId: ["read","write",...]}` + `ownership: {ownerColumn:"ownerId"|null, ownedByRole:roleId|null}` (an owned entity gets/uses an `ownerId` uuid FK→users; the registry marks it so schema_builder emits the column and the data engine scopes queries).
- Per interaction: `allowedRoles:[roleId]` (which roles may fire this button/workflow).

**Enforcement points (generated from the registry):**
1. **Ownership column** — schema_builder emits `ownerId uuid → users.id` for entities flagged `ownership.ownerColumn`; seed + create-workflows set it to the acting user.
2. **Permission-gated data routes** — the `/api/data/[...path]` runtime checks the session user's role against the entity's `access` map (403 on miss); `scope:"own"` roles get an automatic `where ownerId = session.user.id` filter. Emit an `contracts/access-policy.json` the runtime reads.
3. **Permission-gated workflow dispatch** — the workflow engine checks the trigger's `allowedRoles` before running (403 on miss).
4. **Role-based UI gating** — pages/actions carry `visibleForRoles` (from the interaction `allowedRoles`); the renderer hides nav items / actions / create buttons the session role can't use. A guard strips or `disabled`s them so the UI never offers an action the API will 403.

**Enforcement phases (after the naming phases P1–P6):**
- **P7 — access model in the registry**: derive `roles`/entity `access`/`ownership`/interaction `allowedRoles` from the plan's `access_control` + `field_access` + workflow assignment roles; persist `access-policy.json`. Validate every role/permission references a real entity id.
- **P8 — ownership + gated data routes**: schema_builder emits `ownerId`; the data-engine runtime reads `access-policy.json`, enforces role→permission + `scope:"own"` filtering; create-workflows stamp `ownerId`.
- **P9 — gated workflow dispatch**: workflow engine enforces `allowedRoles`.
- **P10 — role-based UI gating**: emit `visibleForRoles`; renderer + a guard hide/disable unauthorized actions/nav.
- **P11 — RBAC E2E**: seed two roles; assert a low-priv role gets 403 on a protected route/workflow and does not see the gated button, while the owner role does.

## Scope boundary (honest)
- IN: the registry as the **single source of truth for names, the relationship graph, the interaction map, AND the access model**, consumed by all generators AND enforced at runtime (data routes, workflow dispatch, UI gating).
- OUT: the behavioral-smoke gate (its own spec) — complementary, not part of this.
- Sequencing: naming authority (P1–P6) ships and fixes `unknown table` first; RBAC enforcement (P7–P11) builds on the settled registry. Each phase is independently green.

## Tests
- `resource_registry.py`: `Equipment` (uncountable) → one consistent `{table, slug}` pair used everywhere; explicit planner `table:"equipment"` hint honored (table=="equipment", not re-pluralized); multi-word entity (`RecruitmentDrive`) name family; FK target resolves to a real entity id; interaction resolves button→workflowId→targetEntityId; legacy dict `entities` + list `data_models` both normalize; idempotent/deterministic (sorted, byte-stable).
- Per-consumer refactor tests: schema_builder/workflow_generator/contract_generator produce the SAME table string for a given entity (a cross-generator agreement test — the anti-`equipment`/`equipments` regression).
- Validator: an interaction/relationship referencing an unknown entity id → error.
- E2E (P6): generated Equipment app — `grep pgTable` name == workflow `db_insert` table.
