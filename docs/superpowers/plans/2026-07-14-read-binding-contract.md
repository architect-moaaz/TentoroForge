# Read-Binding Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every generated read-bound node (Table, List, Chart, ResourceTimeline/Calendar/Timeline/Kanban, Stat) bind to a real registered dataSource at generation time — resolve, rename, or **materialize** the missing filtered/derived dataSource — and fail the build (strict gate) on any that still dangle.

**Architecture:** A new deterministic post-generate pass `read_binding_guard.reconcile_read_bindings` extends the existing `list_data_source_guard` give-up branch to the full binding-prop surface and materializes derived dataSources (decoding `active/recent/upcoming/...` prefixes into real filter/sort/limit using the entity's actual columns). It runs last among read-binding passes. `binding_validator` is broadened to error on any unresolved read binding; `resource_registry_context` is broadened to instruct the page agent to declare a dataSource per read widget.

**Tech Stack:** Python 3 (backend/services), pytest. Tests run from `backend/` with `/usr/local/bin/python3 -m pytest`.

Spec: `docs/superpowers/specs/2026-07-14-read-binding-contract.md`. Read the code map in that spec's tables — the binding-prop-per-node-type table and the pass-order table are authoritative.

---

### Task 1: Semantic-prefix decoder

**Files:**
- Create: `backend/services/read_binding_semantics.py`
- Test: `backend/tests/test_read_binding_semantics.py`

Pure functions, no I/O. Given a binding token and an entity's real column metadata, decode a derived-view intent into `{op_hint, filter, sort, limit}`.

- [ ] **Step 1: Write failing tests**

```python
from services.read_binding_semantics import strip_prefix, decode_view

# prefix stripping → (prefix, base_token)
def test_strip_prefix():
    assert strip_prefix("activeRecruitmentDrives") == ("active", "recruitmentDrives")
    assert strip_prefix("recentApplicants") == ("recent", "applicants")
    assert strip_prefix("upcomingInterviews") == ("upcoming", "interviews")
    assert strip_prefix("recruitmentDrives") == ("", "recruitmentDrives")  # no prefix

# decode uses REAL columns: status enum values + date-ish fields
COLS = {"status": {"type": "varchar", "enum": ["Active", "Closed"]},
        "createdAt": {"type": "timestamp"}, "startsAt": {"type": "timestamp"}}

def test_decode_active_maps_to_status_filter():
    v = decode_view("active", COLS)
    assert v["filter"] == {"status": "Active"}

def test_decode_recent_sorts_desc_limits():
    v = decode_view("recent", COLS)
    assert v["sort"] == {"field": "createdAt", "direction": "desc"}
    assert v["limit"] == 5
    assert "filter" not in v

def test_decode_upcoming_sorts_asc_on_future_date():
    v = decode_view("upcoming", COLS)
    assert v["sort"]["direction"] == "asc"
    assert v["limit"] == 5

def test_decode_no_status_column_omits_filter():
    v = decode_view("active", {"createdAt": {"type": "timestamp"}})
    assert "filter" not in v  # no status column → do not invent one

def test_decode_empty_prefix_is_plain_list():
    assert decode_view("", COLS) == {}
```

- [ ] **Step 2: Run to verify fail** — `/usr/local/bin/python3 -m pytest tests/test_read_binding_semantics.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement.** `strip_prefix`: match a leading known prefix from `{active,open,recent,latest,new,upcoming,pending,closed,completed,top}` (longest-first, case-insensitive) followed by an uppercase letter; return `(prefix_lower, remainder_with_leading_char_lowered)`. `decode_view(prefix, cols)`:
  - pick a status-like column: first col whose name ∈ {status,state,stage} with an `enum` list; map prefix→value by case-insensitive membership (`active`→first enum matching "active"/"open"; `pending`→"pending"; `closed`/`completed`→matching). Only set `filter` if a value matched.
  - pick a date-like column: first of {createdAt,created_at,insertedAt} for `recent/latest/new` (sort desc); for `upcoming` first of {startsAt,scheduledAt,dueAt,startDate,date} (sort asc). Set `limit:5` for recent/latest/new/upcoming/top.
  - `top` → sort desc on a numeric-ish column if present else createdAt, limit 5.
  - unknown/empty prefix → `{}`.
  Return only the keys that apply.

- [ ] **Step 4: Run to verify pass.** Same command → PASS.

- [ ] **Step 5: Commit** — `feat(read-binding): semantic prefix decoder for derived views`.

---

### Task 2: Read-binding node/prop walker + resolve/remap

**Files:**
- Create: `backend/services/read_binding_guard.py`
- Test: `backend/tests/test_read_binding_guard.py`

Core walk. Reuse `binding_validator` readers for slugs/entities/columns and `list_data_source_guard._canon`, `_SINGLE_TOKEN_RE`. Define `_READ_BINDINGS` mapping node type (lowercased `type`/`component`) → tuple of binding props, per the spec table (Table→`rows`; List family→`items`; Chart→`data`; ResourceTimeline→`resources`,`items`; Calendar→`events`; Timeline→`entries`; Kanban→`data`; Stat family→`value`,`current`,`count`,`score`). A binding value is a whole-string `{{X}}` (or dotted `{{X.field}}` for stat props).

- [ ] **Step 1: Failing tests** (Class A remap + resolved pass-through only; materialize is Task 3):

```python
import json
from services.read_binding_guard import reconcile_read_bindings

def _write(tmp_path, schema, name="page"):
    (tmp_path/"src"/"schemas").mkdir(parents=True, exist_ok=True)
    (tmp_path/"src"/"db"/"schema").mkdir(parents=True, exist_ok=True)
    (tmp_path/"src"/"schemas"/f"{name}.json").write_text(json.dumps(schema))

def _schema(pg):  # minimal RecruitmentDrive table with status enum
    (pg/"recruitmentDrives.ts").write_text(
        'export const recruitmentDrives = pgTable("recruitmentDrives", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  title: varchar("title", { length: 255 }).notNull(),\n'
        '  status: varchar("status", { length: 50 }),\n'
        '  createdAt: timestamp("created_at"),\n});\n')

def test_resolved_is_noop(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[{"name":"recruitmentDrives","entity":"RecruitmentDrive","op":"list"}],
                      "root":{"type":"Table","rows":"{{recruitmentDrives}}"}})
    r = reconcile_read_bindings(str(tmp_path))
    assert r["actions_by_kind"]["resolved"] >= 1
    d = json.load(open(tmp_path/"src"/"schemas"/"page.json"))
    assert d["root"]["rows"] == "{{recruitmentDrives}}"

def test_class_a_remap(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[{"name":"recruitmentDrives","entity":"RecruitmentDrive","op":"list"}],
                      "root":{"type":"Table","rows":"{{drives}}"}})
    reconcile_read_bindings(str(tmp_path))
    d = json.load(open(tmp_path/"src"/"schemas"/"page.json"))
    assert d["root"]["rows"] == "{{recruitmentDrives}}"
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement** `reconcile_read_bindings(output_dir)`: load registered slugs/entities/columns (via binding_validator readers); for each `src/schemas/**/*.json`, recurse `root`; for each node matched in `_READ_BINDINGS`, for each of its binding props holding a single-token `{{X}}`: (1) if `X` (root of dotted) ∈ page dataSource names → record `resolved`; (2) else unique `_canon` match among page dataSource names of the compatible op → rewrite → `remapped`. (Materialize branch stubbed to record `unresolved` for now.) Return `{files_scanned, files_changed, actions_by_kind:{resolved,remapped,materialized,unresolved}, nodes:[...]}`. Write changed files. Own try/except at module boundary; never raise.

- [ ] **Step 4: Verify pass.**

- [ ] **Step 5: Commit** — `feat(read-binding): node/prop walker with resolve+remap`.

---

### Task 3: Materialize derived dataSources (list / chart / stat / map)

**Files:**
- Modify: `backend/services/read_binding_guard.py`
- Test: `backend/tests/test_read_binding_guard.py`

Fill the materialize branch. Reuse `chart_data_source_guard` series-shaping and `widget_data_source_guard` aggregate/list-shaping helpers where importable; otherwise build the dataSource dict directly.

- [ ] **Step 1: Failing tests**

```python
def test_materialize_active_list(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[{"name":"recruitmentDrives","entity":"RecruitmentDrive","op":"list"}],
                      "root":{"type":"Table","rows":"{{activeRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    d = json.load(open(tmp_path/"src"/"schemas"/"page.json"))
    ds = {s["name"]: s for s in d["dataSources"]}
    assert "activeRecruitmentDrives" in ds
    assert ds["activeRecruitmentDrives"]["entity"] == "RecruitmentDrive"
    assert ds["activeRecruitmentDrives"]["op"] == "list"
    assert ds["activeRecruitmentDrives"]["filter"] == {"status": "Active"}
    assert d["root"]["rows"] == "{{activeRecruitmentDrives}}"  # binding untouched, now resolvable

def test_materialize_recent_list_sort_limit(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[{"name":"recruitmentDrives","entity":"RecruitmentDrive","op":"list"}],
                      "root":{"type":"List","items":"{{recentRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    ds = {s["name"]: s for s in json.load(open(tmp_path/"src"/"schemas"/"page.json"))["dataSources"]}
    assert ds["recentRecruitmentDrives"]["sort"]["direction"] == "desc"
    assert ds["recentRecruitmentDrives"]["limit"] == 5

def test_materialize_chart_series(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[],
                      "root":{"type":"Chart","data":"{{recruitmentDrivesByStatus}}"}})
    reconcile_read_bindings(str(tmp_path))
    d = json.load(open(tmp_path/"src"/"schemas"/"page.json"))
    ds = {s["name"]: s for s in d["dataSources"]}
    assert ds["recruitmentDrivesByStatus"]["op"] == "series"
    assert ds["recruitmentDrivesByStatus"].get("groupBy")  # a real column
    assert d["root"]["data"] == "{{recruitmentDrivesByStatus}}"

def test_materialize_stat_aggregate(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[],
                      "root":{"type":"Stat","value":"{{openRecruitmentDrives.count}}"}})
    reconcile_read_bindings(str(tmp_path))
    ds = {s["name"]: s for s in json.load(open(tmp_path/"src"/"schemas"/"page.json"))["dataSources"]}
    assert ds["openRecruitmentDrives"]["op"] == "aggregate"
    assert "count" in ds["openRecruitmentDrives"]["metrics"]

def test_no_real_entity_left_unresolved(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[], "root":{"type":"Table","rows":"{{activeSprockets}}"}})
    r = reconcile_read_bindings(str(tmp_path))
    d = json.load(open(tmp_path/"src"/"schemas"/"page.json"))
    assert d["root"]["rows"] == "{{activeSprockets}}"  # untouched
    assert r["actions_by_kind"]["unresolved"] >= 1

def test_idempotent(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[{"name":"recruitmentDrives","entity":"RecruitmentDrive","op":"list"}],
                      "root":{"type":"Table","rows":"{{activeRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    first = (tmp_path/"src"/"schemas"/"page.json").read_text()
    reconcile_read_bindings(str(tmp_path))
    assert (tmp_path/"src"/"schemas"/"page.json").read_text() == first
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement materialize.** Strip prefix (`read_binding_semantics.strip_prefix`); canonical-match the base to a registered entity slug (reuse `_SlugResolver`). If none → leave `unresolved`. Else pick op by node type (Chart→`series`, Stat→`aggregate`, else `list`); `decode_view(prefix, cols)` for filter/sort/limit. Build the dataSource dict: list→`{name,entity,op:list,**view}`; series→`{name,entity,op:series,groupBy:<status-or-first-enum-or-category col>,agg:{fn:count}}` + set node `data`/`xKey`/`series` like `chart_data_source_guard`; aggregate→`{name,entity,op:aggregate,metrics:{<field>:{fn:count, **(filter if any)}}}` where `<field>` = the dotted metric key. Append to page `dataSources` (dedup by name). Idempotent: if the name already exists, only record `resolved`/`materialized` without appending a duplicate.

- [ ] **Step 4: Verify pass** — full `test_read_binding_guard.py`.

- [ ] **Step 5: Commit** — `feat(read-binding): materialize derived list/chart/stat dataSources`.

---

### Task 4: `data-contract.json` writer

**Files:**
- Modify: `backend/services/read_binding_guard.py`
- Test: `backend/tests/test_read_binding_guard.py`

- [ ] **Step 1: Failing test**

```python
def test_data_contract_written_and_deterministic(tmp_path):
    _schema(tmp_path/"src"/"db"/"schema")
    _write(tmp_path, {"dataSources":[{"name":"recruitmentDrives","entity":"RecruitmentDrive","op":"list"}],
                      "root":{"type":"Table","rows":"{{activeRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    c = json.load(open(tmp_path/"contracts"/"data-contract.json"))
    assert c["version"] == 1
    node = next(n for n in c["nodes"] if n["binding_name"] == "activeRecruitmentDrives")
    assert node["action"] == "materialized"
    assert node["node_type"].lower() == "table"
    assert node["binding_prop"] == "rows"
    first = (tmp_path/"contracts"/"data-contract.json").read_text()
    reconcile_read_bindings(str(tmp_path))
    assert (tmp_path/"contracts"/"data-contract.json").read_text() == first
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — collect per-node records `{file, node_type, binding_prop, binding_name, entity, op, resolved, action}` during the walk; write `<output_dir>/contracts/data-contract.json` with `{version:1, nodes:[...]}`, `json.dumps(..., indent=2, sort_keys=True)`, nodes sorted by `(file, binding_prop, binding_name)`. Mkdir `contracts/`.
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Commit** — `feat(read-binding): emit deterministic data-contract.json`.

---

### Task 5: Wire into `post_generate_fixes`

**Files:**
- Modify: `backend/services/post_generate_fixes.py` (after the final `reconcile_list_sources`, ~line 552)
- Test: `backend/tests/test_read_binding_guard.py` (full-pipeline regression)

- [ ] **Step 1: Failing regression** — build a fixture with a dataSource-rename orphan (`{{drives}}`) AND a derived chart binding, run `apply_post_generate_fixes(output_dir)`, assert the drives rows binding is healed and the chart dataSource materialized.

- [ ] **Step 2: Verify fail** (pass not yet wired).

- [ ] **Step 3: Wire** — after the existing final `reconcile_list_sources` call, add:
```python
    try:
        from services.read_binding_guard import reconcile_read_bindings
        _r = reconcile_read_bindings(output_dir)
        print(f"read_binding_guard: {_r['actions_by_kind']} across {_r['files_changed']} file(s)")
    except Exception as e:  # additive; never break the pipeline
        print(f"read_binding_guard: skipped ({e})")
```

- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Commit** — `feat(read-binding): wire reconciler into post_generate_fixes`.

---

### Task 6: Broaden the validation gate

**Files:**
- Modify: `backend/services/binding_validator.py` (`_LIST_BINDING_KEYS` + `_check_page` read-binding loop, ~lines 85, 362-371)
- Test: `backend/tests/test_binding_validator.py`

- [ ] **Step 1: Failing tests** — a page with a dangling Chart `data:{{foo}}` (no `foo` dataSource) → an `error` with kind `binding_unresolved`; same for ResourceTimeline `resources`, Calendar `events`, Timeline `entries`, and dotted Stat `value:{{foo.count}}` (root `foo` absent). An all-resolved page → `ok:True`.

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — extend the read-binding-key set the page check iterates to `("rows","items","data","resources","events","entries")` plus the stat props `("value","current","count","score")` treated as dotted (validate the root identifier against `ds_names`). Keep them errors. Do NOT flag Chart `series` (config array) or `optionsFrom.source` (already handled).
- [ ] **Step 4: Verify pass** — `test_binding_validator.py`.
- [ ] **Step 5: Commit** — `feat(read-binding): gate errors on all read-node bindings`.

---

### Task 7: Broaden the page-agent authoring context

**Files:**
- Modify: `backend/services/resource_registry_context.py` (the binding-rules block, ~lines 161-174)
- Test: `backend/tests/test_resource_registry_context.py` (create if absent)

- [ ] **Step 1: Failing test** — `build_resource_context(output_dir)` output contains guidance naming Chart/List/map/Stat data binding (not only "Table rows"): assert the emitted string mentions e.g. `Chart` and `dataSource` and "declare" in the rules region.

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — extend the rules text: "Every Table, List, Chart, Calendar/Timeline/ResourceTimeline, and Stat MUST bind its data prop (rows/items/data/events/entries/resources/value) to a page dataSource declared over one of the entities above. For a filtered view (active/recent/upcoming/…) declare the dataSource WITH the filter/sort — never invent a bare binding name."
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Commit** — `feat(read-binding): author-side rules cover charts/maps/stats`.

---

### Task 8: E2E verification on a real app + strict gate

**Files:** none (verification only)

- [ ] **Step 1** — Run the full pass on the live fixture: `reconcile_read_bindings("output/nssnwvv6")`; assert `analytics.json`'s `{{activeRecruitmentDrives}}`/`{{upcomingInterviews}}` and `home.json`'s `{{recentApplicants}}` are now backed by materialized dataSources; `data-contract.json` exists.
- [ ] **Step 2** — Run `binding_validator.validate_bindings("output/nssnwvv6")` before/after; confirm the read-binding error count drops to 0 (or only genuine-no-entity cases remain).
- [ ] **Step 3** — Trigger a live generation with `FORGE_BINDING_GATE=strict`; confirm it does NOT fail on read bindings (they materialize) and the generated dashboards render rows. Record the app slug + before/after in the plan.
- [ ] **Step 4: Commit** — `test(read-binding): e2e verification notes` (if any fixture/docs added).

---

## Self-review notes
- Type consistency: `reconcile_read_bindings` return dict shape (`files_scanned/files_changed/actions_by_kind/nodes`) is used identically in Tasks 2–5 and 8. `decode_view` returns only-applicable keys; callers must treat missing `filter`/`sort`/`limit` as absent.
- Idempotency is tested in Task 3 and enforced by dedup-by-name + leaving already-resolvable bindings untouched.
- The reconciler must run AFTER `schema_references` so it heals rename orphans (Class A) — Task 5 places it after the final `reconcile_list_sources`.
- Do not modify the renderer; the literal-`{{}}` behavior is the signal the gate consumes.
