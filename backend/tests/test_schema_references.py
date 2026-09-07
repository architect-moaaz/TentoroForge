"""The unified reference resolver treats the extracted registry as the authority
over every schema reference: exact → derived → fuzzy → flagged, with a report."""
import json

from services.schema_references import resolve_schema_references, RegistryIndex


def _app(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Member": {"fields": {"id": {"type": "uuid"}, "planId": {"type": "uuid"},
                                  "trainerId": {"type": "uuid"}}},
            "MembershipPlan": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
            "Trainer": {"fields": {"id": {"type": "uuid"}, "fullName": {"type": "varchar"}}},
        },
        "relations": [
            {"from_entity": "Member", "to_entity": "MembershipPlan", "type": "many-to-one"},
            {"from_entity": "Member", "to_entity": "Trainer", "type": "many-to-one"},
        ],
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "members"
    sdir.mkdir(parents=True)
    return sdir


def test_resolves_wrong_entity_and_label_to_reality(tmp_path):
    sdir = _app(tmp_path)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/members/new",
        "dataSources": [
            {"name": "plans", "entity": "Plan", "op": "list"},          # wrong entity
            {"name": "trainers", "entity": "Trainer", "op": "list"},    # correct
        ],
        "root": {"type": "Form", "children": [
            {"type": "Select", "props": {"name": "planId", "label": "Plan",
                                         "optionsFrom": {"source": "plans", "value": "id", "label": "planName"}}},
            {"type": "Select", "props": {"name": "trainerId", "label": "Trainer",
                                         "optionsFrom": {"source": "trainers", "value": "id", "label": "fullName"}}},
        ]},
    }), encoding="utf-8")

    res = resolve_schema_references(str(tmp_path))
    assert res["derived"] >= 2

    d = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    ds = {x["name"]: x for x in d["dataSources"]}
    # "Plan" → MembershipPlan; dataSource renamed to the resolvable slug
    assert "membershipPlans" in ds and ds["membershipPlans"]["entity"] == "MembershipPlan"
    by = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"): by[n["props"]["name"]] = n["props"]
            for v in n.values(): walk(v)
        elif isinstance(n, list):
            for x in n: walk(x)
    walk(d)
    assert by["planId"]["optionsFrom"]["source"] == "membershipPlans"
    assert by["planId"]["optionsFrom"]["label"] == "name"       # real label field
    # the already-correct trainer dropdown is untouched
    assert by["trainerId"]["optionsFrom"]["source"] == "trainers"
    assert by["trainerId"]["optionsFrom"]["label"] == "fullName"


def test_report_written_with_methods(tmp_path):
    sdir = _app(tmp_path)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/members/new",
        "dataSources": [{"name": "plans", "entity": "Plan", "op": "list"}],
        "root": {"type": "Form", "children": [
            {"type": "Select", "props": {"name": "planId", "optionsFrom": {"source": "plans", "label": "x"}}},
        ]},
    }), encoding="utf-8")
    resolve_schema_references(str(tmp_path))
    rep = json.loads((tmp_path / "contracts" / "references-report.json").read_text(encoding="utf-8"))
    kinds = {r["kind"] for r in rep["references"]}
    assert "dataSource.entity" in kinds
    assert any(r["resolved"] == "MembershipPlan" for r in rep["references"])


def test_idempotent(tmp_path):
    sdir = _app(tmp_path)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/members/new",
        "dataSources": [{"name": "membershipPlans", "entity": "MembershipPlan", "op": "list"}],
        "root": {"type": "Form", "children": [
            {"type": "Select", "props": {"name": "planId",
                                         "optionsFrom": {"source": "membershipPlans", "value": "id", "label": "name"}}},
        ]},
    }), encoding="utf-8")
    res = resolve_schema_references(str(tmp_path))
    assert res["derived"] == 0 and res["fuzzy"] == 0     # already reality → nothing to do


def test_unresolvable_dropdown_is_neutralized_not_shipped_broken(tmp_path):
    sdir = _app(tmp_path)
    # References an entity that exists NOWHERE and a FK column with no relation.
    (sdir / "new.json").write_text(json.dumps({
        "route": "/members/new",
        "dataSources": [{"name": "widgets", "entity": "Widget", "op": "list"}],
        "root": {"type": "Form", "children": [
            {"type": "Select", "props": {"name": "widgetRef", "label": "Widget",
                                         "optionsFrom": {"source": "widgets", "value": "id", "label": "name"}}},
        ]},
    }), encoding="utf-8")
    res = resolve_schema_references(str(tmp_path))
    assert res.get("neutralized", 0) >= 1

    d = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    node = d["root"]["children"][0]
    # No dead empty dropdown ships — degraded to a plain Input, optionsFrom stripped.
    assert node["type"] == "Input"
    assert "optionsFrom" not in node["props"]
    rep = json.loads((tmp_path / "contracts" / "references-report.json").read_text(encoding="utf-8"))
    assert any(r["method"] == "neutralized" for r in rep["references"])


def test_missing_dir_safe(tmp_path):
    assert resolve_schema_references(str(tmp_path))["files"] == 0


def test_resolver_canonicalizes_button_workflow_ref(tmp_path):
    """A Button pointing at a drifted workflow name (createMember) is canonicalized
    to the real workflow (CreateMember) so /api/workflows/{name}/execute dispatches."""
    _app(tmp_path)
    wf = tmp_path / "workflows"
    wf.mkdir()
    (wf / "CreateMember.json").write_text(json.dumps(
        {"id": "wf_create_member", "name": "CreateMember", "definition": {"nodes": []}}), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    (sdir / "members.json").write_text(json.dumps({
        "route": "/members",
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Save", "workflow": "createMember"}},
        ]},
    }), encoding="utf-8")
    resolve_schema_references(str(tmp_path))
    listing = json.loads((sdir / "members.json").read_text(encoding="utf-8"))
    assert listing["root"]["children"][0]["props"]["workflow"] == "CreateMember"


def test_resolver_neutralizes_phantom_button_workflow(tmp_path):
    """A Button pointing at a workflow that exists nowhere is neutralized, never
    left dispatching a dead /api/workflows call."""
    _app(tmp_path)
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "CreateMember.json").write_text(json.dumps(
        {"id": "wf_create_member", "name": "CreateMember", "definition": {"nodes": []}}), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    (sdir / "members.json").write_text(json.dumps({
        "route": "/members",
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Frobnicate", "workflow": "doesNotExist"}},
        ]},
    }), encoding="utf-8")
    resolve_schema_references(str(tmp_path))
    listing = json.loads((sdir / "members.json").read_text(encoding="utf-8"))
    assert listing["root"]["children"][0]["props"].get("workflow") != "doesNotExist"


def _helpdesk_app(tmp_path):
    """A ticketing registry: Ticket has requesterId/assigneeId (person-role FKs to
    User) and assetId (real FK to Asset). No Requester/Assignee/Category entity."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "User": {"fields": {"id": {"type": "uuid"}, "fullName": {"type": "varchar"}}},
            "Asset": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
            "Ticket": {"fields": {"id": {"type": "uuid"}, "requesterId": {"type": "uuid"},
                                  "assigneeId": {"type": "uuid"}, "assetId": {"type": "uuid"}}},
        },
        "relations": [
            {"from_entity": "Ticket", "to_entity": "User", "type": "many-to-one", "foreignKey": ""},
            {"from_entity": "Ticket", "to_entity": "Asset", "type": "many-to-one", "foreignKey": ""},
        ],
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas" / "tickets"
    sdir.mkdir(parents=True)
    return sdir


def test_person_role_datasource_and_select_repoint_to_users(tmp_path):
    """The reported bug: `requesterId` derives a phantom `requesters`/`Requester`
    source. It must resolve to the real User entity → dataSource `users` (op list)
    and the Select's optionsFrom.source → `users`, so /api/data/users serves it and
    the dropdown is NOT neutralized."""
    sdir = _helpdesk_app(tmp_path)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/tickets/new",
        "dataSources": [
            {"name": "requesters", "entity": "Requester", "op": "list"},   # phantom role source
            {"name": "assets", "entity": "Asset", "op": "list"},           # real
        ],
        "root": {"type": "Form", "children": [
            {"type": "Select", "props": {"name": "requesterId", "label": "Requester",
                                         "optionsFrom": {"source": "requesters", "value": "id", "label": "fullName"}}},
            {"type": "Select", "props": {"name": "assetId", "label": "Asset",
                                         "optionsFrom": {"source": "assets", "value": "id", "label": "name"}}},
        ]},
    }), encoding="utf-8")

    resolve_schema_references(str(tmp_path))
    d = json.loads((sdir / "new.json").read_text(encoding="utf-8"))

    ds = {x["name"]: x for x in d.get("dataSources", [])}
    assert "requesters" not in ds                       # phantom name gone
    assert "users" in ds and ds["users"]["entity"] == "User"

    by = {}
    def walk(n):
        if isinstance(n, dict):
            if (n.get("props") or {}).get("name"):
                by[n["props"]["name"]] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(d)
    # Select preserved (not degraded to Input) and repointed at the real users slug
    assert by["requesterId"]["type"] == "Select"
    assert by["requesterId"]["props"]["optionsFrom"]["source"] == "users"


def _recruit_app(tmp_path):
    """A recruiting registry: Applicant + RecruitmentDrive — the entities a stub
    dashboard backfill features in "Recent <Entity>" tables."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Applicant": {"fields": {"id": {"type": "uuid"}, "fullName": {"type": "varchar"},
                                     "email": {"type": "varchar"}}},
            "RecruitmentDrive": {"fields": {"id": {"type": "uuid"}, "title": {"type": "varchar"}}},
        },
        "relations": [],
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    return sdir


def _tables_in(root) -> list:
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "Table":
                out.append(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(root)
    return out


def test_renamed_list_source_repoints_table_rows_binding(tmp_path):
    """The dashboard "Recent <Entity>" bug: a `applicantsRecent` list source is
    canonicalized to the entity slug `applicants`, but the Table rows still bind
    `{{applicantsRecent}}`. The rows binding must be repointed to `{{applicants}}`
    so the table renders real data instead of empty."""
    sdir = _recruit_app(tmp_path)
    (sdir / "home.json").write_text(json.dumps({
        "route": "/",
        "dataSources": [
            {"name": "applicantsStats", "op": "aggregate", "entity": "Applicant"},
            {"name": "applicantsRecent", "op": "list", "entity": "Applicant", "limit": 5},
            {"name": "recruitmentDrivesRecent", "op": "list", "entity": "RecruitmentDrive", "limit": 5},
        ],
        "root": {"type": "Stack", "children": [
            {"type": "Table", "props": {"rows": "{{applicantsRecent}}", "columns": []}},
            {"type": "Table", "props": {"rows": "{{recruitmentDrivesRecent}}", "columns": []}},
        ]},
    }), encoding="utf-8")

    resolve_schema_references(str(tmp_path))
    d = json.loads((sdir / "home.json").read_text(encoding="utf-8"))

    list_names = {x["name"] for x in d["dataSources"] if x.get("op") == "list"}
    assert list_names == {"applicants", "recruitmentDrives"}     # canonicalized

    rows = [t["props"]["rows"] for t in _tables_in(d["root"])]
    # rows repointed to survive canonicalization — no dangling `Recent` binding
    assert rows == ["{{applicants}}", "{{recruitmentDrives}}"]


def test_kebab_case_binding_repoints_on_rename(tmp_path):
    """The `_BIND_HEAD` regex must accept hyphens so that a kebab-case
    dataSource name (`assessment-days` from the list-page route slug)
    gets its `{{assessment-days}}` binding rewritten when step (1)
    renames the dataSource to the entity slug (`assessmentDays`).
    Without hyphen support the regex only captures `{{assessment` and
    the binding is left dangling — the Assessment Days table renders
    empty despite the DB having rows."""
    (tmp_path / "contracts").mkdir()
    (tmp_path / "src" / "db" / "schema").mkdir(parents=True)
    (tmp_path / "src" / "schemas").mkdir()
    # Registry with AssessmentDay entity so schema_references can canonicalize.
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"AssessmentDay": {
            "name": "AssessmentDay",
            "table": "assessment_days",
            "fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "title": {"type": "varchar"},
                "scheduledFor": {"type": "timestamp"},
            },
        }},
        "relations": [],
    }), encoding="utf-8")

    (tmp_path / "src" / "schemas" / "assessment-days.json").write_text(json.dumps({
        "route": "/assessment-days",
        "dataSources": [
            # List builder emits the kebab route slug as the dataSource name.
            {"name": "assessment-days", "op": "list", "entity": "AssessmentDay"},
        ],
        "root": {"type": "Stack", "children": [
            {"type": "Table", "props": {
                "rows": "{{assessment-days}}",
                "columns": [{"key": "title", "label": "Title"}],
            }},
        ]},
    }), encoding="utf-8")

    resolve_schema_references(str(tmp_path))
    d = json.loads((tmp_path / "src" / "schemas" / "assessment-days.json").read_text(encoding="utf-8"))

    ds_name = d["dataSources"][0]["name"]
    binding = d["root"]["children"][0]["props"]["rows"]
    assert ds_name == "assessmentDays"
    assert binding == "{{assessmentDays}}", (
        f"binding stayed as {binding!r} — the hyphen in the kebab name "
        f"defeated the repoint regex"
    )


def test_colliding_list_sources_fold_to_one_survivor(tmp_path):
    """When two list sources canonicalize to the SAME slug — a plain `applicants` and
    a `applicantsRecent` — keep one survivor (no duplicate dataSource) and repoint the
    dropped source's binding to the survivor."""
    sdir = _recruit_app(tmp_path)
    (sdir / "home.json").write_text(json.dumps({
        "route": "/",
        "dataSources": [
            {"name": "applicants", "op": "list", "entity": "Applicant"},
            {"name": "applicantsRecent", "op": "list", "entity": "Applicant", "limit": 5},
        ],
        "root": {"type": "Stack", "children": [
            {"type": "Table", "props": {"rows": "{{applicants}}", "columns": []}},
            {"type": "Table", "props": {"rows": "{{applicantsRecent}}", "columns": []}},
        ]},
    }), encoding="utf-8")

    resolve_schema_references(str(tmp_path))
    d = json.loads((sdir / "home.json").read_text(encoding="utf-8"))

    names = [x["name"] for x in d["dataSources"]]
    assert names.count("applicants") == 1       # deduped to a single survivor
    assert "applicantsRecent" not in names

    rows = [t["props"]["rows"] for t in _tables_in(d["root"])]
    # both tables now read the single surviving `applicants` source
    assert rows == ["{{applicants}}", "{{applicants}}"]


def test_phantom_non_role_datasource_is_pruned(tmp_path):
    """A page-level list dataSource whose entity resolves to nothing (not a person
    role, e.g. `Category` with no Category table) is dropped, so the renderer never
    fetches /api/data/categories → 404."""
    sdir = _helpdesk_app(tmp_path)
    (sdir / "new.json").write_text(json.dumps({
        "route": "/tickets/new",
        "dataSources": [
            {"name": "categories", "entity": "Category", "op": "list"},    # phantom, non-role
            {"name": "assets", "entity": "Asset", "op": "list"},           # real
        ],
        "root": {"type": "Form", "children": [
            {"type": "Input", "props": {"name": "title", "label": "Title"}},
        ]},
    }), encoding="utf-8")

    resolve_schema_references(str(tmp_path))
    d = json.loads((sdir / "new.json").read_text(encoding="utf-8"))
    names = {x["name"] for x in d.get("dataSources", [])}
    assert "categories" not in names
    assert "assets" in names
