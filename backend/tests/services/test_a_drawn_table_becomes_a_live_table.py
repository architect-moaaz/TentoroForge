"""A table drawn as text is read from its layers and bound to an entity.

The dashboard's Active Cases table was six cases the designer typed, with a
"View →" per row and no record behind it: the vision pass reads pictures,
and this table is words. The layers say enough — a `Table Row` of headers,
`Table Cell`s at positions, a card titled "Active Cases" — to ask which
entity it lists and which field each column is. The answer is validated as
the vision answer is; unbound, the drawing stays.
"""
import json
from unittest.mock import patch

from services.figma.realize import realize
from services.figma.tables import (
    DrawnTable, classify_tables, describe, detail_route_for_entity, drawn_tables, row_link,
)

CODE = '''
<div className="bg-[#f7f3eb] relative size-full" data-node-id="1:1">
  <div className="bg-white border rounded-[8px] flex flex-col p-[20px]" data-node-id="1:800" data-name="Card">
    <div className="flex justify-between" data-name="PolicyManager"><p className="font-semibold">Active Cases</p><div data-name="Button"><p>+ New Case</p></div></div>
    <div className="h-[564px] overflow-clip relative shrink-0 w-full" data-node-id="1:831" data-name="Table">
      <div className="absolute border-b-2 left-0 top-0 w-[1097px]" data-node-id="1:834" data-name="Table Row">
        <p>Case No</p><p>Type</p><p>Title</p><p>Guest</p><p>Created</p>
      </div>
      <div className="absolute left-0 top-[53px] w-[78px]" data-name="Table Cell"><p>CAS-2024-0441</p></div>
      <div className="absolute left-[94px] top-[53px] w-[60px]" data-name="Table Cell"><p>Refund</p></div>
      <div className="absolute left-[170px] top-[53px] w-[300px]" data-name="Table Cell"><p>Partial refund — HVAC</p></div>
      <div className="absolute left-[486px] top-[53px] w-[120px]" data-name="Table Cell"><p>Sebastian Hartmann</p></div>
      <div className="absolute left-[900px] top-[53px] w-[90px]" data-name="Table Cell"><p>2 Dec 2024</p></div>
      <div className="absolute left-[1034px] top-[53px] w-[62px]" data-name="Table Cell"><p>View →</p></div>
      <div className="absolute left-0 top-[138px] w-[78px]" data-name="Table Cell"><p>CAS-2024-0442</p></div>
      <div className="absolute left-[94px] top-[138px] w-[60px]" data-name="Table Cell"><p>Complaint</p></div>
      <div className="absolute left-[170px] top-[138px] w-[300px]" data-name="Table Cell"><p>Foreign object found</p></div>
      <div className="absolute left-[486px] top-[138px] w-[120px]" data-name="Table Cell"><p>Isabelle Fontaine</p></div>
      <div className="absolute left-[900px] top-[138px] w-[90px]" data-name="Table Cell"><p>2 Dec 2024</p></div>
      <div className="absolute left-[1034px] top-[138px] w-[62px]" data-name="Table Cell"><p>View →</p></div>
    </div>
  </div>
</div>
'''

ENTITIES = [
    {"id": "ENTITY-002", "name": "Case", "fields": [
        {"name": "id"}, {"name": "caseNumber"}, {"name": "caseType"}, {"name": "title"},
        {"name": "requesterName"}, {"name": "createdAt"}]},
    {"id": "ENTITY-001", "name": "User", "fields": [{"name": "email"}]},
]

DOC = {"data": {"entities": ENTITIES},
       "pages": [{"route": "/cases", "data": {"primaryEntity": "ENTITY-002"}},
                 {"route": "/cases/[id]", "data": {"primaryEntity": "ENTITY-002"}}]}


def _answer(payload):
    return lambda **_kw: json.dumps(payload)


GOOD = {"tables": [{"nodeId": "1:831", "entity": "Case", "confidence": 0.9, "reason": "case numbers and types",
                    "columns": [{"label": "Case No", "field": "caseNumber"}, {"label": "Type", "field": "caseType"},
                                {"label": "Title", "field": "title"}, {"label": "Guest", "field": "requesterName"},
                                {"label": "Created", "field": "createdAt"}, {"label": "Brand", "field": "notAField"}]}]}


# ------------------------------------------------------------- extraction

def test_the_table_is_read_from_its_layers():
    (t,) = drawn_tables(CODE)
    assert t.node_id == "1:831"
    assert t.headers == ["Case No", "Type", "Title", "Guest", "Created"]
    assert t.title == "Active Cases"
    assert t.rows[0][:2] == ["CAS-2024-0441", "Refund"] and t.rows[1][0] == "CAS-2024-0442"
    assert t.has_row_action


def test_rows_are_read_left_to_right_whatever_the_layer_order():
    shuffled = CODE.replace('<div className="absolute left-0 top-[53px] w-[78px]" data-name="Table Cell"><p>CAS-2024-0441</p></div>\n', "") \
        .replace('<div className="absolute left-[1034px] top-[53px] w-[62px]" data-name="Table Cell"><p>View →</p></div>',
                 '<div className="absolute left-[1034px] top-[53px] w-[62px]" data-name="Table Cell"><p>View →</p></div>\n'
                 '<div className="absolute left-0 top-[53px] w-[78px]" data-name="Table Cell"><p>CAS-2024-0441</p></div>')
    assert drawn_tables(shuffled)[0].rows[0][0] == "CAS-2024-0441"


def test_a_frame_without_a_table_yields_nothing():
    assert drawn_tables('<div className="relative size-full" data-node-id="1:1"><p>hello</p></div>') == []


def test_the_description_says_what_the_model_needs():
    text = describe(drawn_tables(CODE)[0])
    assert 'titled "Active Cases"' in text and "Case No | Type" in text and "CAS-2024-0441" in text


# --------------------------------------------------------- classification

def test_a_bound_table_keeps_only_the_fields_the_entity_has():
    (entry,) = classify_tables(_answer(GOOD), drawn_tables(CODE), ENTITIES)
    assert entry["entity"] == "Case" and entry["kind"] == "table"
    assert entry["columns"] == ["caseNumber", "caseType", "title", "requesterName", "createdAt"]
    assert entry["columnLabels"]["caseNumber"] == "Case No"
    assert entry["hasRowAction"]


def test_an_entity_the_application_does_not_define_binds_nothing():
    bad = {"tables": [{**GOOD["tables"][0], "entity": "Invoice"}]}
    assert classify_tables(_answer(bad), drawn_tables(CODE), ENTITIES) == []


def test_a_model_failure_costs_only_the_enrichment():
    def boom(**_kw):
        raise RuntimeError("no")
    assert classify_tables(boom, drawn_tables(CODE), ENTITIES) == []


def test_the_row_link_is_the_entitys_detail_page():
    assert detail_route_for_entity(DOC, "Case") == "/cases/[id]"
    assert detail_route_for_entity(DOC, "User") is None


# -------------------------------------------------------------- realising

def test_the_drawing_becomes_a_live_table_whose_rows_open_the_case():
    (entry,) = classify_tables(_answer(GOOD), drawn_tables(CODE), ENTITIES)
    entry["rowHref"] = row_link(detail_route_for_entity(DOC, entry["entity"]))
    tree = {"type": "Container", "props": {}, "children": [
        {"type": "Container", "props": {"_figmaNodeId": "1:831", "className": "relative h-[564px]"},
         "children": [{"type": "Text", "props": {"content": "Case No"}}]}]}
    root, sources, applied = realize(tree, [entry])
    table = root["children"][0]
    assert table["type"] == "Table"
    assert table["props"]["columns"][0] == {"key": "caseNumber", "label": "Case No"}
    assert table["props"]["rowHref"] == "/cases/{{id}}", "the form the Table fills from the row"
    assert table["props"]["data"] == "{{activeCases}}"
    assert sources == [{"name": "activeCases", "op": "list", "entity": "Case", "limit": 25}]
    assert applied[0]["kind"] == "table"


def test_the_composer_runs_it_beside_the_vision_pass():
    import inspect
    from services.blueprint import figma_layout
    src = inspect.getsource(figma_layout.compose)
    assert "_classify_tables(svc, code)" in src
    assert src.index("_classify_regions(") < src.index("_classify_tables(svc, code)") < src.index("_realize.realize(")


def test_the_entitys_own_page_wins_over_another_view_of_it():
    doc = {"data": {"entities": ENTITIES},
           "pages": [{"route": "/front-desk/[id]", "data": {"primaryEntity": "ENTITY-002"}},
                     {"route": "/cases/[id]", "data": {"primaryEntity": "ENTITY-002"}}]}
    assert detail_route_for_entity(doc, "Case") == "/cases/[id]"

