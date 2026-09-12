"""What A2UI accepted must still be what Forge's contract accepts.

Both cases here were measured on a live build: the composer's tree passed the
A2UI catalogue and Forge then refused the converted page — a caption that
arrived as a number, and a key-value block whose required `items` the
converter had dropped as fiction. Translation must not manufacture a
contract violation out of a valid surface.
"""
import json

from services.a2ui_to_forge import translate
from services.blueprint.page_planner import load_catalog, validate_props

REG = {"entities": {"Note": {"slug": "notes", "columns": [
    {"name": "id", "type": "uuid"}, {"name": "title", "type": "varchar"},
    {"name": "body", "type": "text"}, {"name": "createdAt", "type": "timestamp"},
]}}}


def payload(components, data):
    return {"messages": [
        {"version": "v0.9", "updateDataModel": {"value": data}},
        {"version": "v0.9", "updateComponents": {"components": components}},
    ]}


def find(node, kind):
    if node.get("type") == kind:
        return node
    for child in node.get("children") or []:
        hit = find(child, kind)
        if hit:
            return hit
    return None


def test_a_bound_caption_arrives_in_the_type_the_contract_declares():
    comps = [{"id": "root", "component": "Stack", "children": ["tbl"]},
             {"id": "tbl", "component": "Table", "caption": {"path": "/notes/count"},
              "rows": {"path": "/notes/rows"}, "columns": {"path": "/notes/columns"}}]
    data = {"notes": {"count": 6, "rows": [{"title": "a"}],
                      "columns": [{"key": "title", "label": "Title"}]}}
    r = translate(payload(comps, data), REG, route="/notes")
    table = find(r["schema"]["root"], "Table")
    assert table["props"]["caption"] == "6"
    assert validate_props({"root": r["schema"]["root"]}, load_catalog()) == []


def test_copy_with_bound_values_is_kept_and_bound_not_dropped():
    """A record page's metadata block: labels are copy, values are the
    record's. Dropping it as invented rows lost the component and failed
    the page on the `items` KeyValueList requires."""
    comps = [{"id": "root", "component": "Stack", "children": ["h", "meta"]},
             {"id": "h", "component": "Heading", "content": {"path": "/note/title"}},
             {"id": "meta", "component": "KeyValueList", "items": [
                 {"label": "Created", "value": {"path": "/note/createdAt"}},
                 {"label": "Words", "value": {"path": "/note/wordCount"}},
             ]}]
    data = {"note": {"id": "n1", "title": "Groceries", "createdAt": "2026-01-01",
                     "wordCount": 12}}
    r = translate(payload(comps, data), REG, route="/notes/[id]", kind="record")
    block = find(r["schema"]["root"], "KeyValueList")
    assert block is not None, r["warnings"]
    items = block["props"]["items"]
    assert [i["label"] for i in items] == ["Created", "Words"]
    assert all("{{" in i["value"] for i in items), items
    assert "2026-01-01" not in json.dumps(r["schema"])
    assert validate_props({"root": r["schema"]["root"]}, load_catalog()) == []


def test_a_required_data_prop_of_pure_fiction_drops_the_component_not_the_prop():
    comps = [{"id": "root", "component": "Stack", "children": ["h", "meta"]},
             {"id": "h", "component": "Heading", "content": {"path": "/note/title"}},
             {"id": "meta", "component": "KeyValueList", "items": [
                 {"label": "Created", "value": "today"}]}]
    data = {"note": {"id": "n1", "title": "Groceries"}}
    r = translate(payload(comps, data), REG, route="/notes/[id]", kind="record")
    assert find(r["schema"]["root"], "KeyValueList") is None
    assert any("requires 'items'" in w for w in r["warnings"]), r["warnings"]
    assert validate_props({"root": r["schema"]["root"]}, load_catalog()) == []


def test_an_optional_data_prop_of_pure_fiction_is_still_just_dropped():
    comps = [{"id": "root", "component": "Stack", "children": ["h", "lst"]},
             {"id": "h", "component": "Heading", "content": {"path": "/note/title"}},
             {"id": "lst", "component": "List", "items": [{"title": "made up"}]}]
    data = {"note": {"id": "n1", "title": "Groceries"}}
    r = translate(payload(comps, data), REG, route="/notes/[id]", kind="record")
    lst = find(r["schema"]["root"], "List")
    assert lst is not None and "items" not in lst["props"]
    assert "made up" not in json.dumps(r["schema"])


def test_a_dialog_composed_as_its_own_root_is_kept_and_named(tmp_path):
    """The composer writes a Dialog as a second top-level component, opened by
    a button's `opensDialog`. Built from `root` only, it vanished, and the
    page was refused for opening a dialog it did not contain — twice, on two
    builds. It is attached under the root and named by its `id` prop, which
    is what `opensDialog` and the functional check resolve against."""
    from services.blueprint.functional_completeness import page_findings

    comps = [{"id": "root", "component": "Stack", "children": ["h", "del"]},
             {"id": "h", "component": "Heading", "content": {"path": "/note/title"}},
             {"id": "del", "component": "Button", "label": "Delete Note",
              "variant": "danger", "opensDialog": "delete-dialog"},
             {"id": "delete-dialog", "component": "Dialog", "title": "Delete this note?",
              "description": "This cannot be undone.", "size": "sm", "child": "confirm"},
             {"id": "confirm", "component": "Button", "label": "Delete Permanently",
              "variant": "danger", "workflow": "FLOW-003"}]
    data = {"note": {"id": "n1", "title": "Groceries"}}
    r = translate(payload(comps, data), REG, route="/notes/[id]", kind="record")
    dialog = find(r["schema"]["root"], "Dialog")
    assert dialog is not None, r["warnings"]
    assert dialog["props"]["id"] == "delete-dialog"
    assert find(dialog, "Button")["props"]["workflow"] == "FLOW-003"
    assert validate_props({"root": r["schema"]["root"]}, load_catalog()) == []

    # The functional check sees the dialog the button opens.
    doc = {"pages": [{"id": "PAGE-002", "route": "/notes/[id]", "status": "PROPOSED"}],
           "pageLayouts": [{"page": "PAGE-002", "root": r["schema"]["root"],
                            "dataSources": r["schema"]["dataSources"]}],
           "workflows": [{"id": "FLOW-003", "name": "Delete Note",
                          "trigger": {"kind": "manual"}}]}
    rules = {f["rule"] for f in page_findings(doc)}
    assert "dialog-not-defined" not in rules, page_findings(doc)


def test_an_edit_page_is_record_scoped_even_though_a2ui_calls_it_a_form():
    """An edit route (`/notes/[id]/edit`, kind `form`) shows AND edits one
    existing record. It classifies as `form`, not `record`, and its route does
    not END with `]`, so both the converter and the completeness floor once
    treated it as record-less: the metadata block lost the `value` its `items`
    contract requires, and the Save form had no record for its Update workflow
    to name. Measured on a live build — `/records/[id]/edit` was the one page a
    four-page app dropped, 404ing its route.

    The record the `[id]` names is in scope regardless of the declared pattern:
    the `/note/*` pointers bind through a minted `get`-by-id source, and the
    Update workflow's `record` input is satisfied by that same scope."""
    from services.blueprint.functional_completeness import page_findings, unsatisfied_inputs

    comps = [{"id": "root", "component": "Stack", "children": ["meta", "form1"]},
             {"id": "meta", "component": "KeyValueList", "items": [
                 {"label": "Created", "value": {"path": "/note/createdAt"}},
                 {"label": "Title", "value": {"path": "/note/title"}}]},
             {"id": "form1", "component": "Form", "workflow": "FLOW-002",
              "submitLabel": "Save Changes",
              "fields": [{"kind": "text", "name": "title", "label": "Title"}]}]
    data = {"note": {"id": "n1", "title": "Groceries", "createdAt": "2026-01-01"}}
    r = translate(payload(comps, data), REG, route="/notes/[id]/edit",
                  page_id="PAGE-EDIT", kind="form")

    # The metadata values survive as bindings, not stripped as fiction.
    block = find(r["schema"]["root"], "KeyValueList")
    assert block is not None, r["warnings"]
    assert all("{{" in i["value"] for i in block["props"]["items"]), block["props"]["items"]
    assert validate_props({"root": r["schema"]["root"]}, load_catalog()) == []
    # A single get-by-id source is minted for the record the page edits.
    gets = [s for s in r["schema"]["dataSources"]
            if s.get("op") == "get" and s.get("entity") == "Note"]
    assert len(gets) == 1, r["schema"]["dataSources"]

    # The floor: the Save form's Update workflow finds its record in scope.
    doc = {"pages": [{"id": "PAGE-EDIT", "route": "/notes/[id]/edit",
                      "status": "PROPOSED", "data": {"primaryEntity": "Note"}}],
           "pageLayouts": [{"page": "PAGE-EDIT", "root": r["schema"]["root"],
                            "dataSources": r["schema"]["dataSources"]}],
           "data": {"entities": [{"id": "Note", "name": "Note"}]},
           "workflows": [{"id": "FLOW-002", "name": "Update Note",
                          "trigger": {"kind": "manual"},
                          "inputs": [{"name": "record", "kind": "record",
                                      "entity": "Note", "required": True}]}]}
    form = find(r["schema"]["root"], "Form")
    layout = doc["pageLayouts"][0]
    assert unsatisfied_inputs(doc, doc["pages"][0], layout, form, "FLOW-002") == []
    assert "page-not-composed" not in {f["rule"] for f in page_findings(doc)}


def test_a_filterbar_over_a_searchable_table_drops_its_duplicate_search():
    """A data-bound Table renders its own search toolbar. A composer that also
    places a FilterBar above it gives the page two search boxes for one list —
    the duplication that read as a broken, low-density layout on the Master
    Data page. When both are present the FilterBar keeps its filter chips and
    drops its search (showSearch=false); the Table's search stays."""
    comps = [{"id": "root", "component": "Stack", "children": ["bar", "tbl"]},
             {"id": "bar", "component": "FilterBar", "showSearch": True,
              "chips": [{"key": "status", "label": "Status",
                         "options": [{"value": "open", "label": "Open"}]}]},
             {"id": "tbl", "component": "Table", "rows": {"path": "/notes/rows"},
              "columns": {"path": "/notes/columns"}}]
    data = {"notes": {"rows": [{"title": "a"}],
                      "columns": [{"key": "title", "label": "Title"}]}}
    r = translate(payload(comps, data), REG, route="/notes")
    bar = find(r["schema"]["root"], "FilterBar")
    table = find(r["schema"]["root"], "Table")
    assert bar is not None and table is not None, r["warnings"]
    assert bar["props"].get("showSearch") is False, bar["props"]
    # The Table's own search is left intact — it is the single search now.
    assert table["props"].get("searchable") is not False, table["props"]


def test_a_lone_filterbar_keeps_its_search():
    """No Table with search on the page — the FilterBar's own search is the
    only one, so it must not be stripped."""
    comps = [{"id": "root", "component": "Stack", "children": ["bar"]},
             {"id": "bar", "component": "FilterBar", "showSearch": True,
              "chips": [{"key": "status", "label": "Status",
                         "options": [{"value": "open", "label": "Open"}]}]}]
    r = translate(payload(comps, {}), REG, route="/notes")
    bar = find(r["schema"]["root"], "FilterBar")
    assert bar is not None
    assert bar["props"].get("showSearch") is not False, bar["props"]


def test_visible_if_becomes_a_null_test_on_the_bound_record():
    """The composer writes `visibleIf` as the pointer it binds fields from;
    the renderer evaluates FEEL-lite in data scope, so it becomes a null test
    on the record source. A screen that also creates its record shows one of
    two forms this way."""
    comps = [{"id": "root", "component": "Stack", "children": ["h", "create", "edit"]},
             {"id": "h", "component": "Heading", "content": {"path": "/note/title"}},
             {"id": "create", "component": "Form", "workflow": "FLOW-001",
              "visibleIf": "!/note/id", "submitLabel": "Create"},
             {"id": "edit", "component": "Form", "workflow": "FLOW-002",
              "visibleIf": "/note/id", "submitLabel": "Save"}]
    data = {"note": {"id": "n1", "title": "Groceries"}}
    r = translate(payload(comps, data), REG, route="/notes/[id]", kind="record")
    forms = {f["props"]["workflow"]: f for f in r["schema"]["root"]["children"] if f["type"] == "Form"}
    assert forms["FLOW-001"]["visibleIf"] == "notes.id = null"
    assert forms["FLOW-002"]["visibleIf"] == "notes.id != null"
    assert "visibleIf" not in forms["FLOW-001"]["props"]
    assert validate_props({"root": r["schema"]["root"]}, load_catalog()) == []


def test_an_unresolvable_visible_if_is_dropped_and_the_node_stays_visible():
    comps = [{"id": "root", "component": "Stack", "children": ["f"]},
             {"id": "f", "component": "Form", "workflow": "FLOW-001",
              "visibleIf": "/nowhere/id", "submitLabel": "Create"}]
    r = translate(payload(comps, {"nowhere": {}}), REG, route="/notes", kind="collection")
    form = r["schema"]["root"]["children"][0]
    assert "visibleIf" not in form
    assert any("visibleIf" in w for w in r["warnings"])
