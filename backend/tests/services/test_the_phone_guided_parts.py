"""The guided parts of a phone screen: a form that runs a workflow, a button that runs one, a list of records.

On the website they are the palette entries that ask a question first. Here they are built against the phone kit's `WorkflowForm`,
`WorkflowButton` and `ListView`, from what the Blueprint declares. The code is built on the server from names, never from text the
browser sends; and it goes through the phone's real compiler, so a form that leaves out a required input is refused."""
from __future__ import annotations

import pytest

from services.blueprint import native_engineer
from services.blueprint.service import BlueprintService
from services.react_editor import pages, phone_guides as pg, phone_screens as ps, service
from services.react_editor.service import EditorError

needs_toolchain = pytest.mark.skipif(
    not (native_engineer.toolchain_dir() / "node_modules" / "typescript" / "lib" / "typescript.js").is_file(),
    reason="the phone's toolchain is not installed here")

SCREEN = '''import React from "react";
import { Screen as ScreenView, Text, Row, Stack, ListView, ListItem } from "@/ui";
import { useList } from "@/sdk";

export default function Screen() {
  const items = useList("ShoppingItem", {});
  return (
    <ScreenView title="Shopping List">
      <Text variant="caption">Things to buy</Text>
      <Stack gap="sm">
        <Text>Inside</Text>
      </Stack>
      <ListView
        list={items}
        keyExtractor={(item) => item.id}
        renderItem={(item) => (
          <Row gap="sm">
            <Text>{item.name}</Text>
          </Row>
        )}
      />
    </ScreenView>
  );
}
'''


@pytest.fixture
def p(tmp_path, monkeypatch):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Cart Buddy", domain="ops")
    doc = svc.doc
    doc["pages"] = [{"id": "PAGE-001", "name": "Shopping List", "route": "/", "purpose": "The list.",
                     "access": "authenticated", "pattern": "entity_list"}]
    doc["navigation"] = {"style": "topbar", "tree": [{"label": "Shopping List", "page": "PAGE-001"}]}
    doc["mobile"] = {"surface": "native_only", "native": {"enabled": True}, "store": {"bundleId": "com.example.cartbuddy"}}
    doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "ShoppingItem", "table": "shopping_items", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True, "required": True, "unique": True},
        {"name": "name", "type": "string", "required": True}, {"name": "quantity", "type": "string"},
        {"name": "status", "type": "enum", "enumValues": ["needed", "bought"]}]}]}

    def flow(id, name, purpose, inputs, kind):
        return {"id": id, "name": name, "purpose": purpose, "reference": name, "launchedFrom": ["PAGE-001"], "status": "PROPOSED",
                "trigger": {"kind": "manual", "detail": "A person presses it."}, "inputs": inputs, "requirements": [],
                "steps": [{"key": "do", "name": name, "type": "action", "entity": "ENTITY-001", "next": [],
                           "config": {"actionType": kind, "table": "shopping_items", "values": {}}}]}
    doc["workflows"] = [
        flow("FLOW-001", "Add Item to List", "Capture a new thing to buy.", [
            {"name": "name", "kind": "field", "type": "string", "required": True, "description": "The item."},
            {"name": "quantity", "kind": "field", "type": "string", "required": True}], "db_insert"),
        flow("FLOW-002", "Mark Item Bought", "Move an item to bought.", [
            {"name": "item", "kind": "record", "entity": "ENTITY-001", "required": True, "description": "The item."}], "db_update"),
        flow("FLOW-003", "Clear Bought Items", "Remove what is bought.", [], "db_delete"),
    ]
    doc["nativeCode"] = [{"page": "PAGE-001", "screen": SCREEN, "rationale": "r", "requirements": []}]
    doc["designSystem"] = {"colors": {"primary": "#2563EB"}}
    svc.save()
    (tmp_path / "app" / "src" / "app").mkdir(parents=True)
    (tmp_path / "app" / "package.json").write_text("{}")
    monkeypatch.setattr("services.blueprint.projection.project_public_nav", lambda doc, root: "")
    monkeypatch.setattr(pages, "project_code_pages", lambda doc, root: [])
    return service.locate(tmp_path)


def _opened(p):
    return ps.open_screen(p, "PAGE-001")


def _node(opened, type, text=None):
    return next(n for n in opened["model"]["nodes"].values() if n["type"] == type and (text is None or n.get("text") == text))


def _file(p) -> str:
    return (p.root / "native" / "src" / "screens" / "PAGE-001.tsx").read_text(encoding="utf-8")


def _guide(p, o, **spec):
    return ps.add_guided(p, "PAGE-001", base_revision=o["revision"], spec=spec)


# ---- what the dialogs may choose from ---------------------------------------------------------------------------

def test_the_screen_lists_the_workflows_and_the_kinds_of_record_the_dialogs_choose_from(p):
    g = _opened(p)["guides"]
    assert [w["name"] for w in g["workflows"]] == ["Add Item to List", "Mark Item Bought", "Clear Bought Items"]
    assert g["workflows"][0]["key"] == "addItemToList" and g["workflows"][0]["inputs"][0]["name"] == "name"
    assert g["entities"][0]["name"] == "ShoppingItem" and {"name", "quantity"} <= {f["name"] for f in g["entities"][0]["fields"]}


def test_a_part_inside_a_list_row_knows_what_the_row_is_called(p):
    o = _opened(p)
    row = _node(o, "Row")
    assert pg.row_var_at(o["model"]["nodes"], row["id"]) == "item"
    assert pg.row_var_at(o["model"]["nodes"], _node(o, "Stack")["id"]) is None, "a box outside the list has no row"


# ---- the code each one writes ---------------------------------------------------------------------------------------

def test_a_form_has_one_entry_per_input_of_the_workflow():
    wf = {"key": "addItemToList", "name": "Add Item to List", "inputs": [
        {"name": "name", "type": "string", "required": True, "description": "The item."},
        {"name": "dueDate", "type": "date", "required": False}, {"name": "status", "type": "enum", "required": True, "options": ["a", "b"]}]}
    jsx = pg.form_jsx(wf, None)
    assert "workflow={workflows.addItemToList}" in jsx
    assert 'name: { label: "Name", help: "The item." }' in jsx
    assert 'dueDate: { label: "Due Date (optional)", kind: "date" }' in jsx
    assert 'kind: "select", options: [{ label: "a", value: "a" }, { label: "b", value: "b" }]' in jsx


def test_a_form_in_a_list_row_fixes_the_record_to_the_row():
    wf = {"key": "closeJob", "name": "Close job", "inputs": [{"name": "job", "kind": "record", "type": "string", "required": True}]}
    assert "job: { value: item.id }," in pg.form_jsx(wf, "item")


def test_a_button_sends_a_fixed_word_or_the_rows_record():
    add = {"key": "add", "name": "Add", "inputs": [{"name": "name", "type": "string", "required": True},
                                                    {"name": "count", "type": "number", "required": True},
                                                    {"name": "note", "type": "string", "required": False}]}
    jsx = pg.button_jsx(add, "Add one", {"name": "Milk", "count": "3"}, None)
    assert 'input={{ name: "Milk", count: 3 }}' in jsx and "note" not in jsx and '{"Add one"}' in jsx
    close = {"key": "close", "name": "Close", "inputs": [{"name": "item", "kind": "record", "entity": "ShoppingItem", "required": True}]}
    assert "input={{ item: item.id }}" in pg.button_jsx(close, "Done", {}, "item")


def test_a_button_that_acts_on_a_record_is_refused_outside_a_row_and_says_why():
    close = {"key": "close", "name": "Close", "inputs": [{"name": "item", "kind": "record", "entity": "ShoppingItem", "required": True}]}
    with pytest.raises(pg.GuideError) as e:
        pg.button_jsx(close, "Done", {}, None)
    assert "ShoppingItem" in str(e.value) and "row" in str(e.value)


def test_a_number_that_is_not_one_is_refused_in_words():
    add = {"key": "add", "name": "Add", "inputs": [{"name": "count", "type": "number", "required": True}]}
    with pytest.raises(pg.GuideError) as e:
        pg.button_jsx(add, "Add", {"count": "lots"}, None)
    assert "number" in str(e.value)


def test_what_is_typed_is_a_value_and_never_code():
    from services.react_editor import adapter
    add = {"key": "add", "name": "Add", "inputs": [{"name": "name", "type": "string", "required": True}]}
    jsx = pg.button_jsx(add, 'x"}</WorkflowButton><Evil />', {"name": '"}); steal(); ("'}, None)
    m = adapter.model(f"export default function S() {{ return (<>{jsx}</>); }}")
    assert sorted(n["type"] for n in m["nodes"].values() if n["kind"] != "fragment") == ["WorkflowButton"],         "what was typed stayed inside its quotes: the parser sees one button and nothing else"


def test_the_list_reads_the_records_with_a_name_the_screen_does_not_use():
    entity = {"name": "ShoppingItem", "typeName": "ShoppingItem", "fields": [{"name": "name"}, {"name": "quantity"}]}
    statement, jsx = pg.list_parts(entity, "name", "quantity", "const shoppingItemList = 1;")
    assert statement == 'const shoppingItemList2 = useList("ShoppingItem", {});'
    assert 'title={String(row.name ?? "")}' in jsx and 'subtitle={String(row.quantity ?? "")}' in jsx and "list={shoppingItemList2}" in jsx


def test_a_list_cannot_show_a_field_the_record_does_not_have():
    entity = {"name": "ShoppingItem", "typeName": "ShoppingItem", "fields": [{"name": "name"}]}
    with pytest.raises(pg.GuideError):
        pg.list_parts(entity, "price", None, "")


# ---- on a screen ----------------------------------------------------------------------------------------------------------

@needs_toolchain
def test_a_form_is_added_and_the_screen_still_compiles(p):
    o = _opened(p)
    out = _guide(p, o, kind="form", workflow="FLOW-001", place={"parentId": _node(o, "Stack")["id"]})
    text = _file(p)
    assert out["checked"] is True, "a connected part always goes through the compiler"
    assert "<WorkflowForm" in text and "workflow={workflows.addItemToList}" in text
    assert "WorkflowForm" in text.split('from "@/ui"')[0] and "workflows" in text.split('from "@/sdk"')[0]


@needs_toolchain
def test_a_button_that_runs_a_workflow_is_added_with_what_it_sends(p):
    o = _opened(p)
    _guide(p, o, kind="button", workflow="FLOW-003", label="Clear it all", place={"afterId": _node(o, "Text", "Things to buy")["id"]})
    assert '<WorkflowButton workflow={workflows.clearBoughtItems} input={{  }}>{"Clear it all"}</WorkflowButton>' in _file(p)


@needs_toolchain
def test_a_button_that_marks_the_row_is_added_inside_a_list_row(p):
    o = _opened(p)
    _guide(p, o, kind="button", workflow="FLOW-002", label="Bought", place={"parentId": _node(o, "Row")["id"]})
    assert "workflow={workflows.markItemBought} input={{ item: item.id }}" in _file(p)


@needs_toolchain
def test_a_list_of_records_is_added_with_its_read(p):
    o = _opened(p)
    _guide(p, o, kind="list", entity="ShoppingItem", title="name", subtitle="quantity", place={"parentId": _node(o, "ScreenView")["id"]})
    text = _file(p)
    assert 'const shoppingItemList = useList("ShoppingItem", {});' in text
    assert text.index('const shoppingItemList') < text.index("const items"), "the new read is the screen's first line, before its other hooks"
    assert "<ListView list={shoppingItemList}" in text and 'title={String(row.name ?? "")}' in text


@needs_toolchain
def test_a_button_that_leaves_out_what_a_workflow_requires_is_not_saved(p, monkeypatch):
    """The compiler is the net: a hand-made change that sends nothing to a workflow that needs a record does not compile."""
    o = _opened(p)
    before = _file_saved(p)
    monkeypatch.setattr(pg, "button_jsx", lambda wf, label, values, row_var: f"<WorkflowButton workflow={{workflows.{wf['key']}}} input={{{{}}}}>{{\"x\"}}</WorkflowButton>")
    with pytest.raises(EditorError) as e:
        _guide(p, o, kind="button", workflow="FLOW-002", place={"parentId": _node(o, "Stack")["id"]})
    assert e.value.status == 422 and e.value.code == "does-not-compile" and _file_saved(p) == before


def _file_saved(p) -> str:
    return next(r for r in service.load_blueprint(p).doc["nativeCode"] if r["page"] == "PAGE-001")["screen"]


# ---- what is refused ------------------------------------------------------------------------------------------------------

def test_a_workflow_or_record_the_application_does_not_have_is_refused(p):
    o = _opened(p)
    where = {"parentId": _node(o, "Stack")["id"]}
    for spec in ({"kind": "form", "workflow": "FLOW-999"}, {"kind": "list", "entity": "Nope", "title": "x"}, {"kind": "evil"}):
        with pytest.raises(EditorError) as e:
            _guide(p, o, place=where, **spec)
        assert e.value.status == 422 and e.value.code == "guide"
    assert _file_saved(p) == SCREEN


def test_a_part_is_refused_where_nothing_can_hold_it(p):
    o = _opened(p)
    with pytest.raises(EditorError) as e:
        _guide(p, o, kind="form", workflow="FLOW-001", place={"parentId": _node(o, "Text", "Inside")["id"]})
    assert e.value.code == "guide" and "can't go there" in str(e.value)
    with pytest.raises(EditorError):
        _guide(p, o, kind="form", workflow="FLOW-001", place={})


def test_a_change_made_on_an_older_screen_is_refused(p):
    o = _opened(p)
    with pytest.raises(EditorError) as e:
        ps.add_guided(p, "PAGE-001", base_revision="0000000000000000", spec={"kind": "form", "workflow": "FLOW-001", "place": {"parentId": "r0"}})
    assert e.value.status == 409 and e.value.code == "stale"


def test_the_statement_op_is_not_one_the_browser_may_ask_for():
    from routers.react_editor import _PHONE_OPS
    assert "addStatement" not in _PHONE_OPS


def test_the_statement_goes_first_in_the_screens_own_function():
    from services.react_editor import adapter
    src = 'import { Screen } from "@/ui";\nexport default function S() {\n  const [a] = useState(1);\n  if (!a) return null;\n  return (<Screen title="x" />);\n}\n'
    out = adapter.patch(src, [{"op": "addStatement", "code": 'const rows = useList("Job", {});'}], slots=True)
    assert out.index("const rows") < out.index("const [a]") and out.count("const rows") == 1
