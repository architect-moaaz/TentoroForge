"""An observer repair on a composed page edits the tree instead of
re-composing it — held to the same contract, falling back to a full compose
when the edit is unusable or refused."""

import json
from dataclasses import dataclass
from threading import RLock

from services.blueprint.page_patch import (
    apply_edits, build_patch_prompt, findings_of, parse_edits, patch_page_layout,
)


@dataclass
class Spec:
    task_id: str = "T-1"
    node: str = "page_layouts"
    agent: str = "a2ui_pages"
    subject: str = "PAGE-001"
    feedback: str = ""


class Svc:
    def __init__(self, doc):
        self.doc = doc
        self.lock = RLock()
        self.output_dir = "/nowhere"


def _doc(with_layout=True):
    layout = {
        "page": "PAGE-001", "composedBy": "a2ui", "rationale": "composed by A2UI",
        "requirements": ["REQ-012"],
        "dataSources": [
            {"name": "records", "entity": "E-REC", "op": "list"},
            {"name": "female", "entity": "E-REC", "op": "aggregate", "filter": {"gender": "Male"}},
        ],
        "root": {"type": "Stack", "props": {}, "children": [
            {"type": "Button", "props": {"label": "Add Record", "navigate": "/add-data"}, "children": []},
            {"type": "Table", "props": {"data": "{{records}}", "columns": [{"key": "fullName", "label": "Name"}],
                                        "rowActions": [{"label": "Delete", "workflow": "FLOW-D"}]}, "children": []},
        ]},
    }
    return {
        "application": {"id": "t"},
        "data": {"entities": [{"id": "E-REC", "name": "Record", "table": "records",
                               "fields": [{"name": "id", "type": "uuid"}, {"name": "fullName", "type": "string"},
                                          {"name": "gender", "type": "string"}]}]},
        "requirements": [{"id": "REQ-012", "description": "Female card counts Female records."}],
        "pages": [{"id": "PAGE-001", "route": "/master-data", "actions": ["create", "delete"],
                   "requirements": ["REQ-012"], "data": {"primaryEntity": "E-REC"}}],
        "workflows": [{"id": "FLOW-D", "name": "Delete Record", "trigger": {"kind": "manual"},
                       "inputs": [{"name": "record", "kind": "record", "entity": "E-REC", "required": True}],
                       "steps": [{"key": "d", "name": "d", "type": "action", "entity": "E-REC",
                                  "config": {"actionType": "db_delete", "table": "records",
                                             "where": {"id": "{{record.id}}"}}, "next": []}]}],
        "pageLayouts": [layout] if with_layout else [],
    }


FEEDBACK = ("The observer reviewed your output ... Author it again ...\n\n"
            "- [Observer↔Requirement] PAGE-001: REQ-012: The 'female' data source filters on "
            "gender 'Male' instead of 'Female'.")


def _client(reply):
    """A model that answers the schema: `value` travels as JSON text."""
    def call(*, system, user, schema):
        call.seen = (system, user, schema)
        if isinstance(reply, str):
            return reply
        wire = {**reply, "edits": [
            {**e, "value": json.dumps(e["value"])} if "value" in e else e for e in reply["edits"]]}
        return json.dumps(wire)
    return call


def test_the_schema_is_structured_outputs_safe_and_values_are_decoded():
    """The API refuses an empty schema ("accepts any JSON value") — the first
    live patch call was a 400 and fell back to a full compose. `value` is JSON
    text, decoded on the way in; a bare word is taken as that string."""
    from services.blueprint.page_patch import PATCH_SCHEMA
    def no_empty(node):
        if isinstance(node, dict):
            assert node != {}, "an empty schema accepts any JSON value"
            for v in node.values():
                no_empty(v)
        elif isinstance(node, list):
            for v in node:
                no_empty(v)
    no_empty(PATCH_SCHEMA)
    edits, note = parse_edits(json.dumps({"edits": [
        {"op": "replace", "path": "/a", "value": "\"Female\""},
        {"op": "add", "path": "/b/-", "value": "{\"key\": \"rowNumber\", \"label\": \"#\"}"},
        {"op": "replace", "path": "/c", "value": "3"},
        {"op": "replace", "path": "/d", "value": "Female"},
        {"op": "remove", "path": "/e"}], "note": "n"}))
    assert [e.get("value") for e in edits] == ["Female", {"key": "rowNumber", "label": "#"}, 3, "Female", None]


def test_only_the_findings_reach_the_prompt_not_the_replace_everything_framing():
    assert findings_of(FEEDBACK) == ("- [Observer↔Requirement] PAGE-001: REQ-012: The 'female' data "
                                     "source filters on gender 'Male' instead of 'Female'.")
    assert findings_of("no bullets here") == "no bullets here"


def test_the_prompt_carries_the_tree_the_findings_and_the_pages_own_vocabulary():
    doc = _doc()
    catalog = {"Table": {"props": {"properties": {"data": {}, "columns": {}, "rowActions": {}}, "required": ["columns"]}},
               "Button": {"props": {"properties": {"label": {}, "navigate": {}}}},
               "Stack": {"props": {"properties": {}}},
               "Chart": {"props": {"properties": {"series": {}}}}}
    system, user = build_patch_prompt(doc, doc["pages"][0], doc["pageLayouts"][0], FEEDBACK, catalog)
    assert "- Table: data, columns*, rowActions" in system and "Chart" not in system
    assert "REQ-012: Female card counts Female records." in user
    assert '"gender": "Male"' in user and "instead of 'Female'" in user
    assert "Author it again" not in user


def test_edits_apply_to_a_copy_inside_the_tree_only():
    layout = _doc()["pageLayouts"][0]
    out = apply_edits(layout, [{"op": "replace", "path": "/dataSources/1/filter/gender", "value": "Female"}])
    assert out["dataSources"][1]["filter"] == {"gender": "Female"}
    assert layout["dataSources"][1]["filter"] == {"gender": "Male"}     # untouched
    for bad in ([{"op": "replace", "path": "/page", "value": "X"}],
                [{"op": "remove", "path": "/dataSources/9"}]):
        try:
            apply_edits(layout, bad)
        except Exception:
            pass
        else:
            raise AssertionError(bad)


def test_a_patch_that_fixes_the_finding_is_proposed_as_the_repair():
    svc = Svc(_doc())
    said = []
    reply = {"edits": [{"op": "replace", "path": "/dataSources/1/filter/gender", "value": "Female"}],
             "note": "the Female metric now filters on Female"}
    res = patch_page_layout(svc, Spec(feedback=FEEDBACK), _client(reply), tell=said.append)
    assert res is not None
    (prop,) = res.proposals
    assert prop.section == "pageLayouts" and prop.natural_key == "PAGE-001"
    assert prop.body["dataSources"][1]["filter"] == {"gender": "Female"}
    assert prop.body["root"] == svc.doc["pageLayouts"][0]["root"]        # nothing else moved
    assert prop.body["repairedBy"] == "patch" and "repaired in place (1 edit)" in prop.body["rationale"]
    assert said == ["Repaired /master-data in place with 1 edit instead of re-composing it — "
                    "the Female metric now filters on Female."]


def test_an_edit_that_drops_a_control_is_refused_and_falls_back_to_composing():
    svc = Svc(_doc())
    said = []
    reply = {"edits": [{"op": "remove", "path": "/root/children/1/props/rowActions"}], "note": ""}
    assert patch_page_layout(svc, Spec(feedback=FEEDBACK), _client(reply), tell=said.append) is None
    assert said and said[0].startswith("Tried to repair /master-data in place; the edit was refused")
    assert svc.doc["pageLayouts"][0]["root"]["children"][1]["props"]["rowActions"]   # untouched


def test_unusable_replies_and_no_tree_mean_compose_in_full():
    assert patch_page_layout(Svc(_doc(with_layout=False)), Spec(feedback=FEEDBACK), _client({"edits": []})) is None
    assert patch_page_layout(Svc(_doc()), Spec(feedback=FEEDBACK), _client("{ broken")) is None
    assert patch_page_layout(Svc(_doc()), Spec(feedback=FEEDBACK), _client({"edits": []})) is None
    def boom(**kw):
        raise RuntimeError("model down")
    assert patch_page_layout(Svc(_doc()), Spec(feedback=FEEDBACK), boom) is None


def test_the_executor_edits_on_a_repair_and_composes_on_a_first_pass(monkeypatch):
    from services.blueprint import executors as ex
    svc = Svc(_doc())
    calls = []
    def fake_patch(svc_, spec, client, **kw):
        calls.append(("patch", spec.subject)); return "PATCHED"
    monkeypatch.setattr("services.blueprint.page_patch.patch_page_layout", fake_patch)
    run = ex.make_executor(svc, lambda **kw: "{}", usage=None)
    # The a2ui compose path is not reachable here (no output dir); a repair
    # must return the patch before it is tried.
    assert run(Spec(feedback=FEEDBACK)) == "PATCHED"
    assert calls == [("patch", "PAGE-001")]
