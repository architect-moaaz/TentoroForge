# FK-Semantics Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One authority classifies every FK column's *role* (actor / domain / tenancy / plain) from the registry's real FK targets; every layer reads it and the ~8 duplicated, disagreeing name-based `_OWNER_FK` heuristics are deleted.

**Architecture:** `backend/services/fk_semantics.py` computes `{entityId: {column: {role, targetSlug, targetTable, required}}}` from the canonical registry (`column.fk` → target entity), with a schema `.references()` fallback and an actor-NAME fallback ONLY for columns that are *not* a domain FK. A domain FK (target ≠ users) ALWAYS beats the name — that is the bug fix. The pipeline emits `contracts/fk-semantics.json` (backend consumers) and `src/lib/fk-roles.ts` (runtime). Runtime auto-fill and form-field exclusion switch from name-matching to role-reading.

**Tech Stack:** Python 3.11 (backend, pytest from `backend/`), TypeScript runtime templates (`backend/templates/runtime/*`), Node for template harness checks.

**Role taxonomy (the single source of truth):**
- `domain` — `fk` resolves to a NON-users, non-tenancy entity → render a Select bound to the target; NEVER auto-fill; INCLUDE in create/edit forms.
- `actor` — `fk` resolves to the users/reserved table, OR (`fk` is null AND name matches the actor pattern) → auto-fill from `ctx.user.id`; HIDE from forms. (The name fallback preserves today's behavior for constraint-less `createdById`/`authorId`.)
- `tenancy` — target is a workspace/org/tenant entity, or name matches tenancy pattern → server-fill from session; HIDE from forms.
- `plain` — not a FK → normal field.

**Classification priority (first match wins):**
1. `fk` present AND target is users/reserved → `actor`
2. `fk` present AND target is a tenancy entity → `tenancy`
3. `fk` present (any other target) → `domain`   ← real FK beats the name
4. no `fk`, name matches tenancy pattern → `tenancy`
5. no `fk`, name matches actor pattern → `actor`
6. else → `plain`

---

## Task 1: FK role classifier core

**Files:**
- Create: `backend/services/fk_semantics.py`
- Test: `backend/tests/test_fk_semantics.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_fk_semantics.py
from services.fk_semantics import classify_entity_fks, FkRole

def _reg(cols, slug="pets", name="Pet", table="pets"):
    return {"entities": {name: {"name": name, "slug": slug, "table": table,
            "camel": name[0].lower()+name[1:], "columns": cols}}}

def _users_entity(reg):
    reg["entities"]["User"] = {"name": "User", "slug": "users", "table": "users",
                               "camel": "user", "columns": [{"name": "id", "type": "uuid", "fk": None}]}
    reg["entities"]["Owner"] = {"name": "Owner", "slug": "owners", "table": "owners",
                                "camel": "owner", "columns": [{"name": "id", "type": "uuid", "fk": None}]}
    return reg

def test_domain_fk_beats_name():
    # pets.ownerId references the OWNERS entity, not users -> domain, despite the name
    reg = _users_entity(_reg([
        {"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": False},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["ownerId"].role == "domain"
    assert roles["ownerId"].target_slug == "owners"

def test_actor_fk_when_target_is_users():
    reg = _users_entity(_reg([
        {"name": "createdById", "type": "uuid", "fk": "user", "notNull": True},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["createdById"].role == "actor"

def test_actor_name_fallback_when_no_fk():
    # constraint-less createdById (no .references) still auto-fills -> actor
    reg = _users_entity(_reg([
        {"name": "createdById", "type": "uuid", "fk": None, "notNull": True},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["createdById"].role == "actor"

def test_tenancy_by_name_when_no_fk():
    reg = _users_entity(_reg([
        {"name": "workspaceId", "type": "uuid", "fk": None, "notNull": True},
    ]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["workspaceId"].role == "tenancy"

def test_plain_non_fk_column():
    reg = _users_entity(_reg([{"name": "name", "type": "varchar", "fk": None, "notNull": False}]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["name"].role == "plain"

def test_required_flag_from_notnull():
    reg = _users_entity(_reg([{"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": True}]))
    roles = classify_entity_fks("Pet", reg)
    assert roles["ownerId"].required is True
```

- [ ] **Step 2: Run tests, verify they fail** — `cd backend && /usr/local/bin/python3 -m pytest tests/test_fk_semantics.py -v` → ImportError.

- [ ] **Step 3: Implement `fk_semantics.py`**

```python
"""The ONE authority on what a foreign-key column MEANS.

Every layer used to decide "is this an ownership column?" by matching the column
NAME against a private `_OWNER_FK` set (~8 copies, none agreeing, none reading the
schema). `pets.ownerId` -> the OWNERS table broke all of them: they saw the name
`ownerId`, assumed the users table, and auto-filled the current user's id into a
column that references a domain entity -> FK violation.

This module classifies each column's ROLE from the registry's REAL fk target, so a
genuine FK to a domain table can never again be mistaken for a user-ownership marker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RESERVED_USER_SLUGS = {"users", "user"}
_TENANCY_NAMES = {"workspaceid", "tenantid", "orgid", "organizationid", "accountid"}
_ACTOR_NAME_RE = re.compile(
    r"^(recruiter|owner|user|author|creator|assignee|assigned_?to|reviewer|approver|"
    r"manager|actor|(created|updated|submitted|requested|uploaded|reported|posted)_?by)_?id$",
    re.I,
)


@dataclass(frozen=True)
class FkRole:
    column: str
    role: str            # "domain" | "actor" | "tenancy" | "plain"
    target_slug: str | None = None
    target_table: str | None = None
    required: bool = False


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _resolve_target(reg: dict, fk: str) -> dict | None:
    """Resolve a column.fk value (an entity id/slug/name) to its entity dict."""
    ents = reg.get("entities") or {}
    want = _norm(fk)
    for name, e in ents.items():
        if not isinstance(e, dict):
            continue
        for form in (name, e.get("name"), e.get("slug"), e.get("table"),
                     e.get("camel"), e.get("id"), e.get("singular")):
            if form and _norm(form) == want:
                return e
    return None


def _is_users(entity: dict | None) -> bool:
    if not entity:
        return False
    return any(_norm(entity.get(k)) in {_norm(s) for s in RESERVED_USER_SLUGS}
               for k in ("slug", "table", "name", "id"))


def _is_tenancy_entity(entity: dict | None) -> bool:
    if not entity:
        return False
    return _norm(entity.get("slug") or entity.get("table") or "") in {
        "workspaces", "workspace", "tenants", "tenant", "organizations",
        "organization", "orgs", "org", "accounts", "account",
    }


def classify_entity_fks(entity_id: str, registry: dict) -> dict[str, FkRole]:
    ents = registry.get("entities") or {}
    entity = ents.get(entity_id)
    if entity is None:
        want = _norm(entity_id)
        for name, e in ents.items():
            if isinstance(e, dict) and any(
                _norm(e.get(k)) == want for k in ("name", "slug", "table", "camel", "id")
            ):
                entity = e
                break
    if not isinstance(entity, dict):
        return {}

    out: dict[str, FkRole] = {}
    for col in entity.get("columns") or []:
        if not isinstance(col, dict) or not col.get("name"):
            continue
        name = col["name"]
        nn = bool(col.get("notNull"))
        fk = col.get("fk")
        low = _norm(name)
        if fk:
            target = _resolve_target(registry, fk)
            if _is_users(target):
                role = "actor"
            elif _is_tenancy_entity(target):
                role = "tenancy"
            else:
                role = "domain"
            out[name] = FkRole(name, role,
                               target_slug=(target or {}).get("slug") if target else None,
                               target_table=(target or {}).get("table") if target else None,
                               required=nn)
            continue
        # no real FK — fall back to NAME only for non-domain classification
        if low in _TENANCY_NAMES:
            out[name] = FkRole(name, "tenancy", required=nn)
        elif _ACTOR_NAME_RE.match(name):
            out[name] = FkRole(name, "actor", required=nn)
        else:
            out[name] = FkRole(name, "plain", required=nn)
    return out
```

- [ ] **Step 4: Run tests, verify PASS.**

- [ ] **Step 5: Commit** — `git add backend/services/fk_semantics.py backend/tests/test_fk_semantics.py && git commit -m "feat(fk): FK-role classifier — domain FK target beats the column name"`

---

## Task 2: Schema `.references()` fallback + whole-registry classify + artifact

**Files:**
- Modify: `backend/services/fk_semantics.py`
- Test: `backend/tests/test_fk_semantics.py`

- [ ] **Step 1: Failing tests**

```python
def test_classify_registry_returns_all_entities():
    from services.fk_semantics import classify_registry
    reg = _users_entity(_reg([{"name": "ownerId", "type": "uuid", "fk": "owner", "notNull": False}]))
    allroles = classify_registry(reg)
    assert "Pet" in allroles and allroles["Pet"]["ownerId"].role == "domain"

def test_schema_reference_fallback(tmp_path):
    # registry column.fk missing, but schema .references() knows the target
    from services.fk_semantics import classify_registry
    reg = _users_entity(_reg([{"name": "ownerId", "type": "uuid", "fk": None, "notNull": False}]))
    sdir = tmp_path / "src" / "db" / "schema"; sdir.mkdir(parents=True)
    (sdir / "pets.ts").write_text(
        'import { owners } from "./owners";\n'
        'export const pets = pgTable("pets", { ownerId: uuid("owner_id").references(() => owners.id) });\n')
    allroles = classify_registry(reg, output_dir=str(tmp_path))
    assert allroles["Pet"]["ownerId"].role == "domain"
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement.** Add `classify_registry(registry, output_dir=None)`:
  - Loop every entity, call `classify_entity_fks`.
  - If `output_dir` given, call `registry_schema_reconcile.extract_fk_references(output_dir)` → `{table: {col: target_table}}`; for any column whose registry role came out non-`domain`/`plain`-mismatch — specifically any column with `fk is None` that the schema says references a NON-users table — upgrade to `domain` with the resolved target. (Schema is authoritative; never downgrade a domain classification.)
  - Match schema tables to entities via `_norm`.

- [ ] **Step 4: PASS. Step 5: Commit.**

---

## Task 3: Emit artifacts — `contracts/fk-semantics.json` + `src/lib/fk-roles.ts`

**Files:**
- Modify: `backend/services/fk_semantics.py` (add `emit_fk_semantics(output_dir)` + `emit_fk_roles_module(output_dir)`)
- Modify: `backend/services/runtime_injector.py` (call `emit_fk_roles_module` alongside entity-aliases)
- Modify: `backend/routers/generate.py` (call `emit_fk_semantics` after registry build, both pipelines)
- Test: `backend/tests/test_fk_semantics.py`

- [ ] **Step 1: Failing tests** — assert `contracts/fk-semantics.json` has `Pet.ownerId.role == "domain"`; assert `src/lib/fk-roles.ts` contains `export const FK_ROLES` mapping the pets table's `ownerId` to `"domain"` and exposes `fkRole(table, col)`.

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement.**
  - `emit_fk_semantics(output_dir)`: load registry (contracts/resource-registry.json → registry.json), `classify_registry(reg, output_dir)`, write `contracts/fk-semantics.json` as `{entityId: {col: {role, targetSlug, targetTable, required}}}`.
  - `emit_fk_roles_module(output_dir)`: build `{table_name: {column: role}}` keyed by the entity's real `table`, write `src/lib/fk-roles.ts`:
    ```ts
    const FK_ROLES: Record<string, Record<string, string>> = { /* ... */ };
    export function fkRole(table: string, col: string): string {
      return FK_ROLES[table]?.[col] || "plain";
    }
    export function isAutoFillFk(table: string, col: string): boolean {
      const r = fkRole(table, col); return r === "actor" || r === "tenancy";
    }
    export function isDomainFk(table: string, col: string): boolean {
      return fkRole(table, col) === "domain";
    }
    ```
  - Wire `emit_fk_roles_module` into `runtime_injector` right after `_generate_entity_aliases_module`.
  - Wire `emit_fk_semantics` into `generate.py` after the registry is built (both `_run_relay_pipeline` and `_run_figma_relay_pipeline`). Guard with try/except + log; never fail the build.

- [ ] **Step 4: PASS. Step 5: Commit.**

---

## Task 4: Runtime — auto-fill only actor/tenancy, never domain

**Files:**
- Modify: `backend/templates/runtime/data-engine.ts` (create() owner-FK block ~line 240)
- Modify: `backend/templates/runtime/workflows/index.ts` (`_finalizeInsert` ~line 387-410; delete `_OWNER_FKS`/`_OWNER_FK_RE`)
- Verify: node harness in `/tmp`

- [ ] **Step 1:** In `data-engine.ts`, import `{ isAutoFillFk, isDomainFk }` from `./fk-roles` (guard: the module may be absent for registry-less apps — use a local `try`/optional import or a safe default). Replace the hardcoded `["landlordId","ownerId",...]` loop with: for each column of `entity.table`, if `isAutoFillFk(tableName, col)` and `cleanData[col] == null` and `ctx.user?.id` → set to uid. NEVER touch a `isDomainFk` column. Keep the tenancy block but gate on role `tenancy`.
- [ ] **Step 2:** In `workflows/index.ts`, same: replace `_OWNER_FKS`/`_OWNER_FK_RE` with `isAutoFillFk(table, col)`; delete the two constants.
- [ ] **Step 3:** Node harness: register a `pets` table with `ownerId`, assert with `FK_ROLES.pets.ownerId="domain"` the create path does NOT set ownerId=uid; with `createdById="actor"` it DOES.
- [ ] **Step 4: Commit.**

**Fallback contract:** when `src/lib/fk-roles.ts` is absent (older/registry-less app), `fkRole` import fails → the runtime must fall back to the OLD name-based behavior so those apps don't regress. Implement the import as `let fkRole; try { ({fkRole} = require("./fk-roles")); } catch {}` with a name-based default when unset.

---

## Task 5: Backend consumers read roles — delete the 7 `_OWNER_FK` sets

**Files (each: replace local `_OWNER_FK`/name-match with a `fk_semantics` read; a domain FK must NO LONGER be hidden/excluded):**
- Modify: `backend/services/form_field_align.py` (`_OWNER_FK` line 22; keep `_TENANCY_FK` semantics via role)
- Modify: `backend/services/deterministic_pages.py` (`_OWNER_FK` line 30; sites 132/193/218/297)
- Modify: `backend/services/form_scaffold.py` (`_OWNER_FK` line 31; sites 259/342)
- Modify: `backend/services/context_assembler.py` (`_OWNER_FK` line 26; site 114)
- Modify: `backend/services/user_fk_types.py` (`_OWNER_FK_RE` — only rewrite uuid→integer for `actor` role FKs to users, NOT domain FKs)
- Test: extend each module's existing test (or add `test_fk_consumers_use_roles.py`)

- [ ] **Step 1: Failing test** — for a `pets` entity with `ownerId` (domain FK to owners), assert the create-form builder INCLUDES an `ownerId` field (previously excluded) and it is a `Select` bound to `owners`; assert `createdById` (actor) is still excluded.
- [ ] **Step 2: Verify fail** (today ownerId is excluded).
- [ ] **Step 3: Implement** a shared helper `fk_semantics.hidden_fk_columns(entity_id, registry, output_dir=None) -> set[str]` = columns whose role is `actor` or `tenancy` (normalized). Each consumer replaces `col in _OWNER_FK` with `col_norm in hidden` and deletes its local set. Domain FKs fall through to normal field handling (which, combined with `fk_source_guard`, yields a Select).
- [ ] **Step 4: PASS. Step 5: Commit.**

---

## Task 6: Create-form includes domain FK as a Select (end-to-end)

**Files:**
- Verify/Modify: `backend/services/fk_source_guard.py` (already promotes uuid FK Input→Select and points at target — confirm it now fires for the newly-included ownerId)
- Verify: the form-model builder path (`deterministic_pages`/`build_form_page`) surfaces domain FKs
- Test: integration on a synthetic vet registry

- [ ] **Step 1: Failing/あintegration test** — build the CreatePet form from a vet-shaped registry; assert the emitted schema has an `ownerId` `Select` with `optionsFrom.source == "owners"`.
- [ ] **Step 2: Verify fail. Step 3: Fill the gap** (most likely just removing the exclusion in Task 5 is enough; if the builder needs an explicit "include domain FK" branch, add it). **Step 4: PASS. Step 5: Commit.**

---

## Task 7: FilterBar key fix + library rebuild/vendor

**Files:**
- Modify: `packages/library/src/components/FilterBar/FilterBar.tsx` (add `key` to the placeholder `<option>`; add index fallback to the mapped key)

- [ ] **Step 1:** `<option key="__saved_views_placeholder" value="" disabled>` and `key={v.id ?? \`view-${i}\`}` with `(v, i)`.
- [ ] **Step 2:** Rebuild library dist + re-vendor into a running app; verify the console warning is gone.
- [ ] **Step 3: Commit.**

---

## Task 8: Live end-to-end verification on the vet app + regen

**Files:** none (verification) — regenerate `output/h7wdt1q4` artifacts via the emitters; exercise CreatePet.

- [ ] **Step 1:** Run `emit_fk_semantics` + `emit_fk_roles_module` on `output/h7wdt1q4`; confirm `fk-semantics.json` says `Pet.ownerId=domain` and `fk-roles.ts` maps `pets.ownerId="domain"`.
- [ ] **Step 2:** Patch the live app's `data-engine.ts`/`workflows/index.ts` + `fk-roles.ts`; reload; submit CreatePet with an owner selected → row inserts, no FK violation.
- [ ] **Step 3:** Confirm the CreatePet form now shows an Owner Select bound to owners.
- [ ] **Step 4:** Grep the repo: zero remaining `_OWNER_FK` definitions in backend/services + runtime templates. Commit the verification notes / any final fix.

---

## Self-Review Notes
- **No regression for registry-less apps:** Task 4's import fallback + consumers guard on "registry present" keep old name-based behavior when `fk-roles.ts`/registry is absent.
- **Domain FK always beats name** is the single invariant that fixes the class; every task enforces it.
- **Deletions are the point:** the plan is not done until the 7 backend `_OWNER_FK` sets + 2 runtime constants are gone and replaced by role reads.
