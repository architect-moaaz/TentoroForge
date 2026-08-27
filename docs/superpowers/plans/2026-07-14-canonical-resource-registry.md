# Canonical Resource Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** One deterministic Canonical Resource Registry, built once after planning, that owns every entity's name family + relationships + interactions + access model; every generator reads it and no longer derives names independently. Kills the `unknown table` class (schema `equipments` vs workflow `equipment`) structurally, then drives RBAC enforcement.

**Architecture:** `services/resource_registry.py::build_canonical_registry(plan)` computes one frozen record per entity (name/table/slug/camel/schemaFile/columns/fks) via a single normalizer (the promoted `_to_table`/`_to_slug`/`_to_camel`), honoring any planner `table` hint. Persisted to `contracts/resource-registry.json` at generate.py ~line 571 (both pipelines). Consumers flip to read it one phase at a time; each deletes its private pluralizer. RBAC phases add an access model + runtime enforcement.

**Tech Stack:** Python 3 (backend/services). Tests from `backend/` with `/usr/local/bin/python3 -m pytest`.

Spec: `docs/superpowers/specs/2026-07-14-canonical-resource-registry.md`. Seam map is authoritative there.

---

## PHASE 1 — Registry + normalizer (additive; nothing consumes yet)

### Task 1.1: The single normalizer

**Files:**
- Create: `backend/services/name_normalizer.py`
- Test: `backend/tests/test_name_normalizer.py`

Promote the canonical trio into one module (leave `contract_generator`'s copies for now; P2+ delete them). Add a singularizer.

- [ ] **Step 1: Failing tests**
```python
from services.name_normalizer import to_table, to_slug, to_camel, to_singular, name_family

def test_multiword():
    f = name_family("RecruitmentDrive")
    assert f["table"] == "recruitmentDrives"      # camelCase plural
    assert f["slug"] == "recruitment-drives"      # kebab plural
    assert f["camel"] == "recruitmentDrive"
    assert f["id"] == "recruitment-drive"         # kebab SINGULAR (stable join key)
    assert f["singular"] == "recruitmentDrive"

def test_uncountable_equipment():
    # the live bug: must be ONE consistent pair, and honor no double-pluralization surprises
    f = name_family("Equipment")
    assert f["table"] == to_table("Equipment")
    assert f["slug"] == to_slug("Equipment")
    # table and slug agree on plurality (both plural of the SAME base)
    assert f["table"].lower().replace("-", "") == f["slug"].replace("-", "")

def test_table_hint_honored():
    f = name_family("Equipment", table_hint="equipment")
    assert f["table"] == "equipment"              # explicit hint wins, not re-pluralized
    assert f["id"] == "equipment"                 # id stays kebab-singular of the name
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — copy `_to_table`/`_to_slug`/`_to_camel` verbatim from `contract_generator.py:217-240`; add `to_singular(name)` (kebab-singular of PascalCase); `name_family(name, table_hint=None)` returns `{id, name, singular, table, slug, camel, schemaFile, typeFile}` where `table = table_hint or to_table(name)` and `slug`/`schemaFile`/`typeFile` derive from the same base. Keep byte-compatible output with the existing helpers (so P2 is a no-op diff for non-drifting apps).
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Commit** `feat(registry): single name normalizer (promoted canonical trio + singularizer)`.

### Task 1.2: build_canonical_registry

**Files:**
- Create: `backend/services/resource_registry.py`
- Test: `backend/tests/test_resource_registry.py`

- [ ] **Step 1: Failing tests**
```python
from services.resource_registry import build_canonical_registry

def _plan():
    return {
        "data_models": [
            {"name": "Equipment", "table": "equipment",
             "fields": [{"name":"id","type":"uuid","primaryKey":True},
                        {"name":"name","type":"varchar","nullable":False},
                        {"name":"status","type":"varchar","enum_values":["Active","Retired"]}]},
            {"name": "MaintenanceLog",
             "fields": [{"name":"id","type":"uuid","primaryKey":True},
                        {"name":"equipmentId","type":"uuid","nullable":False}]},
        ],
        "relations": [{"from":"MaintenanceLog","to":"Equipment","type":"many-to-one","foreignKey":"equipmentId"}],
        "pages": [{"route":"equipment","actions":[
            {"label":"Add Equipment","workflow":"CreateEquipment","kind":"page_action"}]}],
        "workflows": [{"id":"CreateEquipment"}],
    }

def test_entity_name_family_and_hint():
    r = build_canonical_registry(_plan())
    eq = r["entities"]["Equipment"]
    assert eq["id"] == "equipment"
    assert eq["table"] == "equipment"             # planner hint honored, NOT "equipments"
    assert eq["slug"] and eq["schemaFile"].endswith(".ts")
    assert any(c["name"]=="status" and c["enum"]==["Active","Retired"] for c in eq["columns"])

def test_fk_resolves_to_entity_id():
    r = build_canonical_registry(_plan())
    ml = r["entities"]["MaintenanceLog"]
    fk = next(f for f in ml["fks"] if f["column"]=="equipmentId")
    assert fk["targetEntityId"] == "equipment"

def test_relationship_by_id():
    r = build_canonical_registry(_plan())
    rel = r["relationships"][0]
    assert rel["from"]=="maintenance-log" and rel["to"]=="equipment"

def test_interaction_resolves_workflow_and_target_entity():
    r = build_canonical_registry(_plan())
    it = next(i for i in r["interactions"] if i["label"]=="Add Equipment")
    assert it["workflowId"]=="CreateEquipment"
    assert it["targetEntityId"]=="equipment"       # inferred from workflow/page → entity
    assert it["sourcePage"]=="equipment"

def test_legacy_dict_entities_normalized():
    plan = {"entities":{"Equipment":{"table":"equipment","fields":[{"name":"id","type":"uuid"}]}}}
    r = build_canonical_registry(plan)
    assert r["entities"]["Equipment"]["table"]=="equipment"

def test_deterministic_and_reserved_users():
    r1 = build_canonical_registry(_plan()); r2 = build_canonical_registry(_plan())
    import json; assert json.dumps(r1,sort_keys=True)==json.dumps(r2,sort_keys=True)
    # a User entity maps to reserved users table (auth owns it) — still in registry, table "users"
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — read entities via the `data_models or entities` normalization (mirror `contract_generator._plan_models` + `schema_builder`'s legacy-dict handling). For each: `name_family(name, table_hint=entity.get("table"))`; columns from fields (name/type/notNull/enum via enum_values); fks from `relations` (map `to` entity → `targetEntityId` via name→id). Build `relationships` (from/to as ids). Build `interactions` from `pages[].actions` (workflow name→workflowId; targetEntityId inferred from the page's entity or the workflow name via the entity id set). Reserved `users` → table stays `users`. Deterministic (sorted keys). Return the dict.
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Commit** `feat(registry): build_canonical_registry from plan (entities+relationships+interactions)`.

### Task 1.3: Persist + pipeline wiring (additive)

**Files:**
- Modify: `backend/services/resource_registry.py` (add `write_registry`)
- Modify: `backend/routers/generate.py` (both pipelines, after `ensure_entity_reachability`)
- Test: `backend/tests/test_resource_registry.py`

- [ ] **Step 1: Failing test** — `write_registry(reg, output_dir)` writes `contracts/resource-registry.json` (indent=2, sort_keys=True); re-run byte-identical.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** `write_registry`; in `generate.py` `_run_relay_pipeline` (~line 569, right after `ensure_entity_reachability`) and `_run_figma_relay_pipeline` (~line 1969) add:
```python
    try:
        from services.resource_registry import build_canonical_registry, write_registry
        _canon_reg = build_canonical_registry(plan)
        write_registry(_canon_reg, output_dir)
    except Exception as e:
        logger.warning("build_canonical_registry skipped: %s", e)
```
(Additive — persisted but not yet consumed.)
- [ ] **Step 4: Verify pass** + a smoke: run against a captured plan fixture, assert the file exists.
- [ ] **Step 5: Commit** `feat(registry): persist resource-registry.json in both pipelines (additive)`.

---

## PHASE 2 — schema_builder reads the registry

### Task 2.1: schema_builder consumes registry name family
**Files:** Modify `backend/services/schema_builder.py`; Test `backend/tests/test_schema_builder.py`.
- [ ] Accept an optional `registry` arg (or build it internally from the same plan). Replace `table=_to_table(name)`/`slug=_to_slug(name)`/FK `_to_table(ref)` with registry lookups by entity id. Column snake-casing stays local. **Regression:** existing `test_schema_builder.py` must still pass byte-identical for non-drifting entities; add a test that an entity with a planner `table` hint emits `pgTable("<hint>")`. Delete `schema_builder`'s now-unused `_to_table`/`_to_slug`. Commit `feat(registry): schema_builder names tables from the registry`.

---

## PHASE 3 — workflow_generator + contract_generator + app_model read registry (CLOSES `unknown table`)

### Task 3.1: workflow_generator resolves tables via registry
**Files:** Modify `backend/services/workflow_generator.py`; Test `backend/tests/test_workflow_generator.py`.
- [ ] `_resolve_table(entity)` → registry `entity_id → table` (no independent `_to_table` fallback). Add the **cross-generator agreement test**: for a plan with entity `Equipment` (hint `equipment`), `schema_builder`'s emitted pgTable name == `workflow_generator`'s `db_insert` table string. This is the anti-regression for the live bug. Commit `fix(registry): workflow tables resolve via registry — closes schema/workflow name drift`.

### Task 3.2: contract_generator + app_model_builder read registry
**Files:** Modify `backend/services/contract_generator.py`, `backend/services/app_model_builder.py`; Tests alongside.
- [ ] api-client `/api/data/{slug}`, navigation-flow (fix the divergent inline kebab-singular), seed-plan, and `write_app_model` all read the registry name family. Delete `contract_generator._to_table/_to_slug/_to_camel` once no caller remains (or re-export from `name_normalizer` for back-comat). Commit `feat(registry): contracts + app-model read the registry`.

---

## PHASE 4–6 (naming completion) — outline, detailed after P3 lands
- **P4**: page-agent `resource_registry_context` + seed + guards read the registry; seed `binding_validator._SlugResolver` from it; retire the rename branches of `schema_references`/`workflow_table_guard`/`list_data_source_guard`/`read_binding_guard` (keep validators).
- **P5**: registry validator — every relationship/interaction references a real entity id → error; wire behind `FORGE_BINDING_GATE`.
- **P6**: live E2E — regenerate an Equipment app; assert `grep pgTable` name == workflow `db_insert` table; Create submit succeeds against a seeded row; zero `unknown table`.

## PHASE 7–11 (RBAC enforcement) — outline, detailed after P6 (needs settled registry)
Per spec's "RBAC enforcement" section: P7 access model + `access-policy.json`; P8 ownership column + gated data routes + `scope:own` filter; P9 gated workflow dispatch; P10 role-based UI gating (`visibleForRoles` + renderer/guard); P11 RBAC E2E (two roles, 403 + hidden button for low-priv).

## Self-review notes
- The stable `id` is kebab-singular everywhere; relationships/interactions/fks join on it, never on display strings.
- P1 is fully additive — zero behavior change until P2 flips the first consumer. Each later phase flips exactly one consumer group and deletes its private derivation, keeping the pipeline green.
- `name_family` output must be byte-compatible with today's `_to_table`/`_to_slug` so P2/P3 don't churn non-drifting apps; the ONLY intended output change is where drift previously existed (a fix).
- Honor the planner `table` hint (P1) — this is what stops the pipeline discarding the planner's own intent.
