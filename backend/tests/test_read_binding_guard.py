import json

from services.post_generate_fixes import apply_post_generate_fixes
from services.read_binding_guard import reconcile_read_bindings


def _write(tmp_path, schema, name="page"):
    (tmp_path / "src" / "schemas").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "schemas" / f"{name}.json").write_text(json.dumps(schema), encoding="utf-8")


def _schema(pg):  # minimal RecruitmentDrive table with status enum
    pg.mkdir(parents=True, exist_ok=True)
    (pg / "recruitmentDrives.ts").write_text(
        'export const recruitmentDrives = pgTable("recruitmentDrives", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  title: varchar("title", { length: 255 }).notNull(),\n'
        '  status: varchar("status", { length: 50 }),\n'
        '  createdAt: timestamp("created_at"),\n});\n', encoding="utf-8")


def _entity_schema(pg, slug):  # a generic table `<slug>` with a plain status column
    pg.mkdir(parents=True, exist_ok=True)
    (pg / f"{slug}.ts").write_text(
        f'export const {slug} = pgTable("{slug}", {{\n'
        '  id: uuid("id").primaryKey(),\n'
        '  name: varchar("name", { length: 255 }).notNull(),\n'
        '  status: varchar("status", { length: 50 }),\n'
        '  createdAt: timestamp("created_at"),\n});\n', encoding="utf-8")


def _workflow(tmp_path, table, statuses, name="wf"):
    """Write a workflow whose db_insert sets `status` to each literal in `statuses` —
    the real, workflow-harvested status vocabulary for `table`."""
    wdir = tmp_path / "workflows"
    wdir.mkdir(parents=True, exist_ok=True)
    nodes = [
        {"id": f"n{i}", "data": {"config": {
            "actionType": "db_insert", "table": table, "values": {"status": s}}}}
        for i, s in enumerate(statuses)
    ]
    (wdir / f"{name}.json").write_text(json.dumps({
        "id": name, "name": name, "definition": {"nodes": nodes}}), encoding="utf-8")


# ── Task 2: resolve + remap ──────────────────────────────────────────────────

def test_resolved_is_noop(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{recruitmentDrives}}"}})
    r = reconcile_read_bindings(str(tmp_path))
    assert r["actions_by_kind"]["resolved"] >= 1
    d = json.load(open(tmp_path / "src" / "schemas" / "page.json"))
    assert d["root"]["rows"] == "{{recruitmentDrives}}"


def test_class_a_remap(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{drives}}"}})
    reconcile_read_bindings(str(tmp_path))
    d = json.load(open(tmp_path / "src" / "schemas" / "page.json"))
    assert d["root"]["rows"] == "{{recruitmentDrives}}"


# ── Task 3: materialize ──────────────────────────────────────────────────────

def test_materialize_active_list(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    # Real status vocabulary includes "Active" (workflow-harvested) → filter verified.
    _workflow(tmp_path, "recruitmentDrives", ["Active", "Closed"])
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{activeRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    d = json.load(open(tmp_path / "src" / "schemas" / "page.json"))
    ds = {s["name"]: s for s in d["dataSources"]}
    assert "activeRecruitmentDrives" in ds
    assert ds["activeRecruitmentDrives"]["entity"] == "RecruitmentDrive"
    assert ds["activeRecruitmentDrives"]["op"] == "list"
    assert ds["activeRecruitmentDrives"]["filter"] == {"status": "Active"}
    assert d["root"]["rows"] == "{{activeRecruitmentDrives}}"  # binding untouched, now resolvable


def test_materialize_recent_list_sort_limit(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "List", "items": "{{recentRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    ds = {s["name"]: s for s in json.load(open(tmp_path / "src" / "schemas" / "page.json"))["dataSources"]}
    assert ds["recentRecruitmentDrives"]["sort"]["direction"] == "desc"
    assert ds["recentRecruitmentDrives"]["limit"] == 5


def test_materialize_chart_series(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [],
                      "root": {"type": "Chart", "data": "{{recruitmentDrivesByStatus}}"}})
    reconcile_read_bindings(str(tmp_path))
    d = json.load(open(tmp_path / "src" / "schemas" / "page.json"))
    ds = {s["name"]: s for s in d["dataSources"]}
    assert ds["recruitmentDrivesByStatus"]["op"] == "series"
    assert ds["recruitmentDrivesByStatus"].get("groupBy")  # a real column
    assert d["root"]["data"] == "{{recruitmentDrivesByStatus}}"


def test_materialize_stat_aggregate(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [],
                      "root": {"type": "Stat", "value": "{{openRecruitmentDrives.count}}"}})
    reconcile_read_bindings(str(tmp_path))
    ds = {s["name"]: s for s in json.load(open(tmp_path / "src" / "schemas" / "page.json"))["dataSources"]}
    assert ds["openRecruitmentDrives"]["op"] == "aggregate"
    assert "count" in ds["openRecruitmentDrives"]["metrics"]


def test_no_real_entity_left_unresolved(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [], "root": {"type": "Table", "rows": "{{activeSprockets}}"}})
    r = reconcile_read_bindings(str(tmp_path))
    d = json.load(open(tmp_path / "src" / "schemas" / "page.json"))
    assert d["root"]["rows"] == "{{activeSprockets}}"  # untouched
    assert r["actions_by_kind"]["unresolved"] >= 1


def test_idempotent(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{activeRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    first = (tmp_path / "src" / "schemas" / "page.json").read_text(encoding="utf-8")
    reconcile_read_bindings(str(tmp_path))
    assert (tmp_path / "src" / "schemas" / "page.json").read_text(encoding="utf-8") == first


# ── Task 4: data-contract.json ───────────────────────────────────────────────

def test_data_contract_written_and_deterministic(tmp_path):
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{activeRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    c = json.load(open(tmp_path / "contracts" / "data-contract.json"))
    assert c["version"] == 1
    node = next(n for n in c["nodes"] if n["binding_name"] == "activeRecruitmentDrives")
    assert node["action"] == "materialized"
    assert node["node_type"].lower() == "table"
    assert node["binding_prop"] == "rows"
    first = (tmp_path / "contracts" / "data-contract.json").read_text(encoding="utf-8")
    reconcile_read_bindings(str(tmp_path))
    assert (tmp_path / "contracts" / "data-contract.json").read_text(encoding="utf-8") == first


# ── Task 5: wired into the full post_generate_fixes pipeline ──────────────────

def test_post_generate_fixes_runs_read_binding_reconciler(tmp_path):
    """apply_post_generate_fixes must invoke reconcile_read_bindings as its final
    read-binding pass. A Timeline `entries` bound to a DERIVED `{{recent<Entity>}}`
    with no such dataSource is materialized by the END of the whole pipeline — a
    node type only read_binding_guard covers (list_data_source_guard keys on
    rows/items/bind/source, not `entries`), so this isolates the wiring. Also asserts
    the read-binding-only artifact contracts/data-contract.json is emitted."""
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "Timeline", "entries": "{{recentRecruitmentDrives}}"}})
    apply_post_generate_fixes(str(tmp_path))
    d = json.load(open(tmp_path / "src" / "schemas" / "page.json"))
    ds = {s["name"]: s for s in d["dataSources"]}
    assert "recentRecruitmentDrives" in ds  # derived dataSource materialized by the pipeline
    assert ds["recentRecruitmentDrives"]["entity"] == "RecruitmentDrive"
    assert ds["recentRecruitmentDrives"]["op"] == "list"
    assert ds["recentRecruitmentDrives"]["limit"] == 5  # decoded from the `recent` prefix
    # data-contract.json is written by NO other pass — its presence proves the wiring.
    assert (tmp_path / "contracts" / "data-contract.json").exists()


# ── Part 2: status filter verified against real vocabulary, else omitted ──────

def test_status_filter_uses_exact_workflow_vocabulary_casing(tmp_path):
    """A verbatim status-value prefix (`{{shortlistedApplicants}}`) materializes a
    filter using the EXACT casing from the app's real (workflow-harvested) status
    vocabulary — never a capitalized guess. Real value is lowercase "shortlisted";
    the filter value must be exactly "shortlisted"."""
    _entity_schema(tmp_path / "src" / "db" / "schema", "applicants")
    _workflow(tmp_path, "applicants", ["Applied", "shortlisted"])
    _write(tmp_path, {"dataSources": [{"name": "applicants", "entity": "Applicant", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{shortlistedApplicants}}"}})
    reconcile_read_bindings(str(tmp_path))
    ds = {s["name"]: s for s in json.load(open(tmp_path / "src" / "schemas" / "page.json"))["dataSources"]}
    assert "shortlistedApplicants" in ds
    assert ds["shortlistedApplicants"]["op"] == "list"
    assert ds["shortlistedApplicants"]["filter"] == {"status": "shortlisted"}  # exact vocab casing


def test_status_filter_omitted_when_no_real_value_matches(tmp_path):
    """`{{activeThings}}` over an entity whose ONLY real statuses are
    ["draft","published"] → the 'active' token set {active,open} matches neither, so
    the filter is OMITTED (materialized as a plain, non-empty list) rather than
    guessing "Active" (which would match zero rows)."""
    _entity_schema(tmp_path / "src" / "db" / "schema", "things")
    _workflow(tmp_path, "things", ["draft", "published"])
    _write(tmp_path, {"dataSources": [{"name": "things", "entity": "Thing", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{activeThings}}"}})
    reconcile_read_bindings(str(tmp_path))
    ds = {s["name"]: s for s in json.load(open(tmp_path / "src" / "schemas" / "page.json"))["dataSources"]}
    assert "activeThings" in ds
    assert ds["activeThings"]["op"] == "list"
    assert "filter" not in ds["activeThings"]  # no verified value → no filter at all


def test_status_filter_backward_compat_with_captured_enum(tmp_path):
    """Backward-compat: when the real vocabulary contains "Active", the lifecycle
    prefix still filters on "Active" (decode_view enum-match path)."""
    _schema(tmp_path / "src" / "db" / "schema")
    _workflow(tmp_path, "recruitmentDrives", ["Active", "Closed"])
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{activeRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    ds = {s["name"]: s for s in json.load(open(tmp_path / "src" / "schemas" / "page.json"))["dataSources"]}
    assert ds["activeRecruitmentDrives"]["filter"] == {"status": "Active"}


def test_status_filter_omitted_when_no_vocabulary_available(tmp_path):
    """No workflows / no captured enum at all → a lifecycle prefix produces NO filter
    (the whole point: never emit a value not known to exist)."""
    _schema(tmp_path / "src" / "db" / "schema")
    _write(tmp_path, {"dataSources": [{"name": "recruitmentDrives", "entity": "RecruitmentDrive", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{activeRecruitmentDrives}}"}})
    reconcile_read_bindings(str(tmp_path))
    ds = {s["name"]: s for s in json.load(open(tmp_path / "src" / "schemas" / "page.json"))["dataSources"]}
    assert "activeRecruitmentDrives" in ds
    assert "filter" not in ds["activeRecruitmentDrives"]


def test_status_vocabulary_idempotent(tmp_path):
    """Re-run byte-identical with the vocabulary-verified filter path."""
    _entity_schema(tmp_path / "src" / "db" / "schema", "things")
    _workflow(tmp_path, "things", ["draft", "published"])
    _write(tmp_path, {"dataSources": [{"name": "things", "entity": "Thing", "op": "list"}],
                      "root": {"type": "Table", "rows": "{{activeThings}}"}})
    reconcile_read_bindings(str(tmp_path))
    first = (tmp_path / "src" / "schemas" / "page.json").read_text(encoding="utf-8")
    reconcile_read_bindings(str(tmp_path))
    assert (tmp_path / "src" / "schemas" / "page.json").read_text(encoding="utf-8") == first
