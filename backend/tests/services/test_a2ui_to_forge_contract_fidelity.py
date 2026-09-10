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
