# Form-Model Correctness for Generated Create Forms — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make generated create-forms field-model-correct: foreign keys render as relational Selects (not date/text pickers), enums/types map from the real SQL column type (not name substrings), lifecycle/audit columns are excluded, and required fields are included and marked with an asterisk.

**Architecture:** A correct, registry-driven form builder already exists — `deterministic_pages.build_form_page` / `_input_for` / `_editable_columns` / `_is_required` (FK→`Select`+`optionsFrom`, SQL-type→control, `validators.required`, Card + 2-col Grid, FK dataSources). But the create-route builder `create_page_coverage.build_create_page` emits plain `Input`s, and the post-pass `semantic_field_types._decide` then re-types by **unanchored name regex** ("candi**date**Id"→DatePicker, "pipelineSt**age**"→NumberInput) with no FK awareness. Fix = (1) route `build_create_page` through `build_form_page`; (2) exclude workflow-managed lifecycle `*At` timestamps; (3) harden `_decide` so the universal retype pass is FK-aware and anchored (protects LLM-built forms too). Required markers need NO library change — `Input`/`Select` already render `*` from `validators.required`.

**Tech Stack:** Python 3 (backend only). Tests from `backend/` with `/usr/local/bin/python3 -m pytest`. No library/renderer change.

---

## Verified facts (do not re-investigate)
- `create_page_coverage.build_create_page(route, entity, cols, workflow)` (`backend/services/create_page_coverage.py:140`) emits `{"type":"Input", ...}` per column name; callers `ensure_create_pages` (`:257`) and `ensure_create_pages_llm` (`:176`) pass `cols` = name list from `_entity_fields` (`:88`, drops only `id/createdat/updatedat/deletedat`).
- `deterministic_pages.build_form_page(entity, columns, route, design_spec, op="create", entities=None)` (`backend/services/deterministic_pages.py:272`) is the correct builder. `_input_for` (`:216`) maps: FK (`_is_fk`, case-sensitive `endsWith("Id")`, `:111`)→`Select`+`optionsFrom {source,value:"id",label}`; jsonb→`KeyValueInput`; boolean→`Switch`; date/timestamp→`DatePicker`; int/numeric→`NumberInput`; text→`Textarea`; email/password→`Input`. Required (`_is_required`, `:206` = `nullable is False and not hasDefault`) adds `validators:{required:True}` on Input/Select/DatePicker/Textarea. `_editable_columns` (`:195`) drops PK/`_SYSTEM`/`_OWNER_FK`. `build_form_page` also emits one `dataSources` list entry per FK Select and wraps in Heading+Card+Grid(≥7 fields)/Stack+Row footer.
- Registry column metadata (`output/<slug>/registry.json`, via `registry_extractor.py`): per column `type`, `primaryKey`, `nullable`, `hasDefault`, `enum_values` (only from `.$type<>`). FK-ness is NOT a column field — inferred by `endsWith Id` (+ `relations` for the target entity). Example `Application`: `candidateId`(uuid,notNull,FK→Candidate), `recruitmentDriveId`(uuid,notNull,FK→RecruitmentDrive), `status`(varchar,hasDefault), `pipelineStage`(varchar,notNull), `keywordScore`(int,nullable), `recruiterNotes`(text,nullable), `shortlistedAt/rejectedAt/offeredAt`(timestamp,nullable — lifecycle).
- `semantic_field_types._decide` (`backend/services/semantic_field_types.py:164`): unanchored regexes `_DATE_RE`/`_QTY_RE`/etc. (`:35-51`); FK-blind; skips fields already having `optionsFrom` (`:224`).
- `Input.tsx:86` / `Select.tsx:62` already render `<span>*</span>` when `validators?.required === true`. **No library change needed for required markers.**

## File Structure
- **Modify** `backend/services/deterministic_pages.py` — add lifecycle-timestamp exclusion to `_editable_columns`; add `validators` to NumberInput/Switch in `_input_for` so required numeric/bool fields also mark.
- **Modify** `backend/services/create_page_coverage.py` — `build_create_page` delegates to `build_form_page`; callers pass column metadata + registry entities.
- **Modify** `backend/services/semantic_field_types.py` — harden `_decide`: FK-first, anchored regexes, prefer SQL type.
- **Tests**: `backend/tests/test_form_model_correctness.py` (new), plus additions to existing `semantic_field_types`/`create_page` tests if present.

---

### Task 1: Exclude workflow-managed lifecycle `*At` timestamps + mark required numeric/bool

**Files:** Modify `backend/services/deterministic_pages.py`. Test: `backend/tests/test_form_model_correctness.py`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/test_form_model_correctness.py
from services.deterministic_pages import _editable_columns, _input_for

_APP_COLS = {
    "id": {"type": "uuid", "primaryKey": True},
    "candidateId": {"type": "uuid", "nullable": False},
    "status": {"type": "varchar", "nullable": False, "hasDefault": True},
    "keywordScore": {"type": "integer", "nullable": False},
    "shortlistedAt": {"type": "timestamp", "nullable": True},
    "rejectedAt": {"type": "timestamp", "nullable": True},
    "createdAt": {"type": "timestamp", "nullable": False, "hasDefault": True},
}

def test_editable_columns_drops_lifecycle_timestamps():
    cols = dict(_editable_columns(_APP_COLS))
    assert "shortlistedAt" not in cols and "rejectedAt" not in cols   # lifecycle → excluded
    assert "createdAt" not in cols                                    # system → excluded
    assert "candidateId" in cols and "status" in cols and "keywordScore" in cols

def test_required_number_gets_validators():
    node = _input_for("keywordScore", {"type": "integer", "nullable": False})
    assert node["type"] == "NumberInput"
    assert node["props"].get("validators", {}).get("required") is True
```

- [ ] **Step 2: Run — expect FAIL** (`shortlistedAt` currently kept; NumberInput has no validators).
Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_form_model_correctness.py -q`

- [ ] **Step 3: Implement**
In `deterministic_pages.py`, add near the `_SYSTEM` set:
```python
import re as _re
# Lifecycle timestamps a WORKFLOW sets (shortlistedAt, rejectedAt, approvedAt, …) — a
# user creating/editing a row should never hand-enter these. createdAt/updatedAt are
# already covered by _SYSTEM; this catches the domain-specific *At columns.
_LIFECYCLE_AT = _re.compile(r"(?:^|_)[a-z0-9]+_?at$", _re.I)

def _is_lifecycle_timestamp(name: str, meta: dict) -> bool:
    low = name.lower()
    if low in _SYSTEM:
        return True
    typ = str((meta or {}).get("type", "")).lower()
    return typ.startswith(("timestamp", "date", "time")) and bool(_LIFECYCLE_AT.search(name)) \
        and low not in ("date",)  # a column literally named "date" is user data, keep it
```
Then in `_editable_columns` (`:195`), extend the skip check:
```python
        if meta.get("primaryKey") or low in _SYSTEM or low in _OWNER_FK \
                or _is_lifecycle_timestamp(name, meta):
            continue
```
In `_input_for` (`:242-243`), add validators to the numeric branch and (`:238-239`) the boolean branch:
```python
    if typ in ("boolean", "bool"):
        return {"type": "Switch", "props": {"name": col, "label": label, **validators}}
    ...
    if typ in _NUMERIC or any(typ.startswith(p) for p in ("int", "numeric", "decimal", "float", "double")):
        return {"type": "NumberInput", "props": {"name": col, "label": label, **validators}}
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** `git commit -m "feat(forms): exclude lifecycle *At timestamps + mark required numeric/bool fields"`

---

### Task 2: Route `build_create_page` through the registry-driven `build_form_page`

**Files:** Modify `backend/services/create_page_coverage.py`. Test: `backend/tests/test_form_model_correctness.py`.

- [ ] **Step 1: Write the failing test**
```python
import json
from services.create_page_coverage import build_create_page

_ENTITIES = {
    "Application": {"fields": {
        "id": {"type": "uuid", "primaryKey": True},
        "candidateId": {"type": "uuid", "nullable": False},
        "recruitmentDriveId": {"type": "uuid", "nullable": False},
        "status": {"type": "varchar", "nullable": False, "hasDefault": True},
        "pipelineStage": {"type": "varchar", "nullable": False},
        "keywordScore": {"type": "integer", "nullable": True},
        "shortlistedAt": {"type": "timestamp", "nullable": True},
    }},
    "Candidate": {"fields": {"id": {"type": "uuid", "primaryKey": True}, "fullName": {"type": "varchar"}}},
    "RecruitmentDrive": {"fields": {"id": {"type": "uuid", "primaryKey": True}, "title": {"type": "varchar"}}},
}

def _nodes(page):
    found = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") in ("Input","Select","NumberInput","DatePicker","Textarea","Switch","KeyValueInput"):
                found.append(n)
            for c in (n.get("children") or []): walk(c)
            for c in ([n.get("root")] if n.get("root") else []): walk(c)
    walk(page)
    return found

def test_build_create_page_is_field_model_correct():
    cols = _ENTITIES["Application"]["fields"]
    page = build_create_page("/applications/new", "Application", cols, "CreateApplication", _ENTITIES)
    by = {n["props"]["name"]: n for n in _nodes(page) if n["props"].get("name")}
    # FK → relational Select with optionsFrom, NOT a DatePicker/text
    assert by["candidateId"]["type"] == "Select"
    assert by["candidateId"]["props"]["optionsFrom"]["source"]  # e.g. "candidates"
    assert by["recruitmentDriveId"]["type"] == "Select"
    # enum-ish varchar stays Input/Select — NEVER a NumberInput
    assert by["pipelineStage"]["type"] != "NumberInput"
    # required (notNull, no default) → validators.required present
    assert by["candidateId"]["props"].get("validators", {}).get("required") is True
    # lifecycle timestamp excluded
    assert "shortlistedAt" not in by
    # a Card wraps the form (layout)
    assert '"Card"' in json.dumps(page)
```

- [ ] **Step 2: Run — expect FAIL** (current build_create_page emits plain Inputs, keeps shortlistedAt, no Card).

- [ ] **Step 3: Implement**
Change `build_create_page` to delegate to `build_form_page`, accepting column metadata + entities:
```python
def build_create_page(route: str, entity: str, cols, workflow: str, entities: dict | None = None) -> dict:
    from services.deterministic_pages import build_form_page
    # `cols` may be a metadata dict {name: meta} (preferred) or a legacy name list.
    if isinstance(cols, dict):
        columns = cols
    else:
        columns = {c: {} for c in (cols or [])}  # legacy: no metadata → best-effort types
    page = build_form_page(entity, columns, route, design_spec=None, op="create",
                           entities=entities or {})
    page["id"] = route.strip("/").replace("/", "-")
    return page
```
Update callers to pass metadata + entities. In `ensure_create_pages` (`:257`) and `ensure_create_pages_llm` (`:176`): instead of `cols` (name list from `_entity_fields`), pass the entity's raw `fields` dict and the full registry entities. Add a helper:
```python
def _entity_columns(registry: dict) -> dict[str, dict]:
    """entity name → its columns metadata dict (name→meta), unfiltered (build_form_page filters)."""
    out = {}
    for name, ent in (registry.get("entities") or {}).items():
        if isinstance(ent, dict):
            f = ent.get("fields")
            out[name] = f if isinstance(f, dict) else {
                c.get("name"): c for c in (f or []) if isinstance(c, dict) and c.get("name")}
    return out
```
At each `build_create_page(route, entity, cols, f"Create{entity}")` call site (`:233`, `:250`, `:278`), replace `cols` with `cols_meta[entity]` (from `_entity_columns(registry)`) and add `registry.get("entities") or {}` as the `entities` arg. Keep the segment→entity resolution unchanged. (If `_entity_fields`/`_SKIP_COLS` are now unused, leave them — `_input_type`/`_humanize` may still be referenced; do not delete without checking.)

- [ ] **Step 4: Run — expect PASS.** Also run `cd backend && /usr/local/bin/python3 -m pytest tests/ -k "create_page or form" -q` — fix any caller/signature breakage.

- [ ] **Step 5: Commit** `git commit -m "feat(forms): create-page builder uses registry-driven fields (FK selects, types, required, card)"`

---

### Task 3: Harden `semantic_field_types._decide` (FK-aware, anchored) so the retype pass can't re-break types

**Files:** Modify `backend/services/semantic_field_types.py`. Test: `backend/tests/test_form_model_correctness.py`.

- [ ] **Step 1: Write the failing test**
```python
from services.semantic_field_types import _decide

def test_fk_column_not_retyped_to_datepicker():
    # candidateId must NOT become a DatePicker (the "candiDATE" substring bug)
    kind, _ = _decide("candidateId", "uuid", options=None)
    assert kind != "DatePicker"

def test_enum_varchar_not_retyped_to_number():
    # pipelineStage must NOT become a NumberInput (the "stAGE" substring bug)
    kind, _ = _decide("pipelineStage", "varchar", options=None)
    assert kind != "NumberInput"

def test_real_date_still_datepicker():
    kind, _ = _decide("startDate", "timestamp", options=None)
    assert kind == "DatePicker"

def test_real_quantity_still_number():
    kind, _ = _decide("keywordScore", "integer", options=None)
    assert kind == "NumberInput"
```

- [ ] **Step 2: Run — expect FAIL** (candidateId→DatePicker, pipelineStage→NumberInput today).

- [ ] **Step 3: Implement**
In `_decide` (`semantic_field_types.py:164`), before the name-regex branches:
```python
    # A foreign-key column is a relational picker, never a scalar control. Detect it
    # first so "candidateId" (contains "date") / "driveId" don't fall to date/number.
    if _re_fk.search(name):          # _re_fk = re.compile(r"[A-Za-z0-9]Id$")  (case-sensitive Id suffix)
        return None, None            # leave for the FK-aware scaffold/build pass to make a Select
```
Add module-level `_re_fk = re.compile(r"[A-Za-z0-9]Id$")`. Then make the type checks win over name substrings and anchor the name regexes so they don't match mid-word:
- Prefer the SQL `type` (`t`) over the name regex: only fall to `_QTY_RE`/`_DATE_RE`/`_MONEY_RE` name matching when `t` is empty/`varchar`/`char`. If `t` is a real numeric/date/text/bool type, map by type. Keep the existing Select branch first (enum).
- Anchor the date regex to whole-word/suffix: replace substring `date` matching with `(?:^|_|\b)date\b` and the `_at$` suffix on the **raw** column (already anchored). Anchor `_QTY_RE` so "age"/"stage" don't match — require word-boundary or suffix (e.g. `\b(qty|quantity|count|score|amount|age)\b` won't match "stage"; verify "stage" is excluded, "age" as its own word still matches).

Concretely, restructure the ordering to:
1. enum (options present) → Select (unchanged),
2. FK (`_re_fk`) → None,
3. type-driven: `t` in numeric → NumberInput; `t` in date/timestamp → DatePicker; `t`==boolean → Switch; `t` in text → Textarea,
4. only if `t` empty/varchar/char: fall back to the (now anchored) name regexes,
5. else None.

- [ ] **Step 4: Run — expect PASS.** Regression: `cd backend && /usr/local/bin/python3 -m pytest tests/ -k "semantic or field or form" -q` — report counts; fix any existing semantic_field_types test that encoded the old substring behavior (update it to the corrected expectation and note why).

- [ ] **Step 5: Commit** `git commit -m "fix(forms): semantic field retype is FK-aware + type-first + anchored (no candidate→date, stage→number)"`

---

### Task 4: End-to-end verification on the real app registry

**Files:** none (verification only).

- [ ] **Step 1:** Run the builder on the real `output/0faexxaw` Application entity and assert the corrected form:
```
cd backend && /usr/local/bin/python3 - <<'PY'
import json
from services.create_page_coverage import build_create_page, _entity_columns
reg = json.load(open("../output/0faexxaw/registry.json"))
cols = _entity_columns(reg)
page = build_create_page("/applications/new", "Application", cols["Application"], "CreateApplication", reg["entities"])
print(json.dumps(page, indent=2)[:1] and "built")
# print each field name → type + optionsFrom + required
def walk(n):
    if isinstance(n, dict):
        if n.get("type") in ("Input","Select","NumberInput","DatePicker","Textarea","Switch","KeyValueInput"):
            p=n["props"]; print(f"  {p.get('name'):22} {n['type']:12} optionsFrom={p.get('optionsFrom',{}).get('source') if isinstance(p.get('optionsFrom'),dict) else None} required={p.get('validators',{}).get('required')}")
        for c in (n.get('children') or []): walk(c)
        if n.get('root'): walk(n['root'])
walk(page)
PY
```
Expected: `candidateId`→Select(optionsFrom candidates, required True), `recruitmentDriveId`→Select(required True), `status`→Input/Select (NOT NumberInput), `pipelineStage`→Input/Select (NOT NumberInput), `keywordScore`→NumberInput, `recruiterNotes`→Textarea, no `shortlistedAt/rejectedAt/offeredAt`.

- [ ] **Step 2:** Regenerate the app's create-form schemas by re-running the coverage pass over `output/0faexxaw` (or note that a fresh generation will produce them), then re-render `/applications/new` (or `/inbox/new`) in the browser at http://localhost:3011 and screenshot — confirm FK Selects, required asterisks, Card layout, no lifecycle timestamps.

- [ ] **Step 3:** Full form/page suite regression: `cd backend && /usr/local/bin/python3 -m pytest tests/ -k "form or create_page or semantic or deterministic_page" -q`.

## Out of scope
- Library/renderer changes (required markers already render from `validators.required`).
- The modal title/heading mismatch ("New Inbox" vs "New Application") and the page/modal duplication — separate nav/routing issue, note but don't fix here.
- LLM schema-agent prompt changes — the deterministic builder + hardened retype pass cover the field model; prompt guidance is a future improvement.
