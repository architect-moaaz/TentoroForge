"""The move — Blueprint first, and honest when it finds nothing."""

from services.smith.move_dispatcher import _retitle, _route_matches


def _tree():
    return {
        "type": "Stack",
        "children": [
            {"type": "Button", "props": {"label": "Add plant",
                                         "navigate": "/plants/new"}},
            {"type": "Heading", "props": {"content": "Plants"}},
            {"type": "EmptyState", "props": {"message": "None yet"},
             "children": [
                 # The same label twice — a header button and its echo in the
                 # empty state. Renaming one is the bug reported next.
                 {"type": "Button", "props": {"label": "Add plant"}},
             ]},
        ],
    }


def test_every_occurrence_of_a_label_is_renamed():
    tree = _tree()
    assert _retitle(tree, "Add plant", "New plant") == 2
    labels = []

    def walk(n):
        if isinstance(n, dict):
            p = n.get("props") or {}
            if "label" in p:
                labels.append(p["label"])
            for c in n.get("children") or []:
                walk(c)

    walk(tree)
    assert labels == ["New plant", "New plant"]


def test_a_label_nobody_uses_changes_nothing():
    tree = _tree()
    assert _retitle(tree, "Export", "Download") == 0


def test_only_visible_text_props_are_matched():
    """`navigate` holds /plants/new. A prop that is not text someone can read
    is not something they would name, and matching it edits the wrong thing."""
    tree = {"type": "Button",
            "props": {"label": "Go", "navigate": "/plants/new"}}
    assert _retitle(tree, "/plants/new", "/elsewhere") == 0
    assert tree["props"]["navigate"] == "/plants/new"


def test_a_route_matches_itself_and_its_schema_path():
    """Understanding returns whichever of the two the Blueprint slice showed
    it; refusing one turns a good understanding into a no-op."""
    assert _route_matches("/plants", "/plants")
    assert _route_matches("/plants", "src/schemas/plants.json")
    assert _route_matches("/plants/[id]", "src/schemas/plants/[id].json")


def test_an_unrelated_route_does_not_match():
    assert not _route_matches("/settings", "src/schemas/plants.json")
    assert not _route_matches("", "src/schemas/plants.json")
    assert not _route_matches("/plants", "")


def test_a_request_that_names_nothing_is_not_a_move():
    """No label, nothing to find — and a removal with no Blueprint behind it
    is None too, so run_iteration reports no_op rather than inventing an edit."""
    from services.smith.move_dispatcher import move_dispatcher

    assert move_dispatcher({"element_label": "Export", "new_value": ""},
                           "/tmp/nope") is None
    assert move_dispatcher({"element_label": "", "new_value": "x"},
                           "/tmp/nope") is None


def test_a_missing_blueprint_is_not_a_crash():
    from services.smith.move_dispatcher import move_dispatcher

    assert move_dispatcher(
        {"element_label": "Add plant", "new_value": "New plant",
         "target_file": "/plants"},
        "/tmp/definitely-not-a-project",
    ) is None


# --- removal ------------------------------------------------------------------

def _project(tmp_path):
    """A list page whose Delete is a Table row action running the delete
    workflow, and whose Add is a Button to the create form — the two shapes a
    control takes, and the two ways it serves a declared verb."""
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Master Data", domain="data")
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Record", "table": "records",
                                     "fields": [{"name": "id", "type": "uuid"},
                                                {"name": "fullName", "type": "string", "required": True}]}]}
    svc.doc["pages"] = [
        {"id": "PAGE-001", "name": "Master Data", "route": "/master-data", "pattern": "entity_list",
         "purpose": "Manage records.", "actions": ["view_record", "edit_record", "delete", "create"],
         "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-002", "name": "Add Record", "route": "/add-data", "pattern": "form", "purpose": "Add.",
         "actions": ["create"], "data": {"primaryEntity": "ENTITY-001"}},
    ]
    svc.doc["workflows"] = [
        {"id": "FLOW-001", "name": "Create Record", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-002"],
         "inputs": [{"name": "fullName", "kind": "field", "required": True}],
         "steps": [{"key": "i", "name": "i", "type": "action", "entity": "ENTITY-001",
                    "config": {"actionType": "db_insert", "table": "records", "values": {"fullName": "{{fullName}}"}},
                    "next": []}]},
        {"id": "FLOW-003", "name": "Delete Record", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"],
         "inputs": [{"name": "record", "kind": "record", "entity": "ENTITY-001", "required": True}],
         "steps": [{"key": "d", "name": "d", "type": "action", "entity": "ENTITY-001",
                    "config": {"actionType": "db_delete", "table": "records", "where": {"id": "{{record.id}}"}},
                    "next": []}]},
    ]
    root = {"type": "Stack", "props": {}, "children": [
        {"type": "Row", "props": {}, "children": [
            {"type": "Heading", "props": {"content": "Master Data"}, "children": []},
            {"type": "Button", "props": {"label": "Add Record", "navigate": "/add-data"}, "children": []}]},
        {"type": "Table", "props": {"data": "{{records}}", "columns": [{"key": "fullName", "label": "Name"}],
                                    "rowActions": [{"label": "Edit", "navigate": "/add-data?id={{id}}"},
                                                   {"label": "Delete", "variant": "danger", "workflow": "FLOW-003"}]},
         "children": []},
    ]}
    svc.upsert("pageLayouts", {"page": "PAGE-001", "root": root, "composedBy": "a2ui",
                               "dataSources": [{"name": "records", "entity": "Record", "op": "list"}]},
               natural_key="PAGE-001")
    svc.save()
    return svc


def _controls(root):
    out = []
    def walk(n):
        if isinstance(n, dict):
            p = n.get("props") or {}
            if n.get("type") == "Button":
                out.append(("Button", p.get("label")))
            for a in p.get("rowActions") or []:
                out.append(("rowAction", a.get("label")))
            for c in n.get("children") or []:
                walk(c)
    walk(root)
    return out


def _stub_projection(monkeypatch):
    calls = []
    def fake(svc, app_root):
        calls.append(app_root)
        return {"files": ["src/schemas/master-data.json"]}
    monkeypatch.setattr("services.blueprint.projection.apply_frontend_projection", fake)
    return calls


def test_a_row_action_is_removed_and_the_page_stops_declaring_what_it_did(tmp_path, monkeypatch):
    """"Remove the delete button" on a list whose Delete is a Table row action.
    The control goes, the page no longer declares `delete` (or the completeness
    rules would demand the control back), and the delete workflow is no longer
    launched from the page (or the composer would bind it again)."""
    from services.blueprint.service import BlueprintService
    from services.smith.move_dispatcher import move_dispatcher
    _project(tmp_path)
    calls = _stub_projection(monkeypatch)
    move = move_dispatcher({"element_label": "Delete", "new_value": "", "target_file": "/master-data"},
                           str(tmp_path))
    assert move is not None and move.touched_paths == ["src/schemas/master-data.json"]
    assert move.move_name.startswith("remove 'Delete' from PAGE-001")
    assert "no longer declares delete" in move.move_name
    assert "Delete Record is no longer launched from it" in move.move_name
    assert calls == [str(tmp_path / "app")]
    svc = BlueprintService.load(output_dir=str(tmp_path))
    layout = next(l for l in svc.doc["pageLayouts"] if l["page"] == "PAGE-001" and l.get("status") != "SUPERSEDED")
    assert _controls(layout["root"]) == [("Button", "Add Record"), ("rowAction", "Edit")]
    page = next(p for p in svc.doc["pages"] if p["id"] == "PAGE-001")
    assert page["actions"] == ["view_record", "edit_record", "create"]
    flow = next(w for w in svc.doc["workflows"] if w["id"] == "FLOW-003")
    assert flow["launchedFrom"] == []


def test_a_button_to_the_create_form_is_removed_and_create_is_retracted(tmp_path, monkeypatch):
    from services.blueprint.service import BlueprintService
    from services.smith.move_dispatcher import move_dispatcher
    _project(tmp_path)
    _stub_projection(monkeypatch)
    move = move_dispatcher({"element_label": "Add Record", "new_value": "", "target_file": "/master-data"},
                           str(tmp_path))
    assert move is not None
    svc = BlueprintService.load(output_dir=str(tmp_path))
    layout = next(l for l in svc.doc["pageLayouts"] if l["page"] == "PAGE-001" and l.get("status") != "SUPERSEDED")
    assert _controls(layout["root"]) == [("rowAction", "Edit"), ("rowAction", "Delete")]
    page = next(p for p in svc.doc["pages"] if p["id"] == "PAGE-001")
    assert page["actions"] == ["view_record", "edit_record", "delete"]
    # the delete workflow still runs from the row action: still launched from the page
    assert next(w for w in svc.doc["workflows"] if w["id"] == "FLOW-003")["launchedFrom"] == ["PAGE-001"]


def test_a_label_the_page_does_not_have_removes_nothing(tmp_path, monkeypatch):
    from services.smith.move_dispatcher import move_dispatcher
    _project(tmp_path)
    calls = _stub_projection(monkeypatch)
    assert move_dispatcher({"element_label": "Delete Record", "new_value": "", "target_file": "/master-data"},
                           str(tmp_path)) is None
    assert calls == []


def test_a_rename_reaches_a_row_action():
    tree = {"type": "Table", "props": {"rowActions": [{"label": "Delete", "workflow": "FLOW-003"},
                                                      {"label": "Edit", "navigate": "/x/{{id}}"}]}}
    assert _retitle(tree, "Delete", "Remove") == 1
    assert [a["label"] for a in tree["props"]["rowActions"]] == ["Remove", "Edit"]
