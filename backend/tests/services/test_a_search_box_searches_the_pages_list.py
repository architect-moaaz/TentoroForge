"""A drawn search box searches the list it sits above.

The design's search box was a layer named "Text Input" holding its
placeholder; the transform knew "Search Input" and "Input" by name and
nothing else, so the box became a paragraph of grey text. The runtime had
search all along — a list source takes `search`, the page passes the URL's
`q`, a manifest of text columns says what matches — and nothing connected a
box to it. Now an input layer is known by its name, a search box is an
`Input type="search"` named `q`, and the composer refuses a search box on a
page with nothing to search, saying which half is missing.
"""
import json
from pathlib import Path

from services.blueprint.functional_completeness import functional_findings
from services.jsx_to_schema import transform_jsx_to_schema

JSX = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <div className="h-[50px] relative w-full" data-node-id="1:2" data-name="Container">
        <div className="absolute bg-[#fdfbf6] border left-0 top-0 w-[355px]" data-node-id="1:3" data-name="Text Input">
          <p className="text-[#a09890]">Search policies...</p>
        </div>
      </div>
      <div className="bg-white border w-[355px]" data-node-id="1:4" data-name="Text Input"><p>Enter guest name</p></div>
    </div>
  );
}
'''


def _find(node, node_id):
    if isinstance(node, dict):
        if (node.get("props") or {}).get("_figmaNodeId") == node_id:
            return node
        for c in node.get("children") or []:
            hit = _find(c, node_id)
            if hit:
                return hit
    return None


def test_the_contract_knows_a_search_input():
    cat = json.loads(Path("contracts/component-catalog.json").read_text())
    comps = cat.get("components") or cat
    inp = comps["Input"] if isinstance(comps, dict) else next(i for i in comps if (i.get("type") or i.get("name")) == "Input")
    assert "search" in inp["props"]["properties"]["type"]["enum"]


def test_a_layer_named_text_input_is_an_input():
    root = transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    plain = _find(root, "1:4")
    assert plain["type"] == "Input" and plain["props"]["placeholder"] == "Enter guest name"
    assert plain["props"].get("type", "text") != "search"


def test_a_search_box_is_the_pages_search():
    root = transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    box = _find(root, "1:3")
    assert box["type"] == "Input"
    assert box["props"]["type"] == "search" and box["props"]["name"] == "q"
    assert box["props"]["placeholder"] == "Search policies..."


def _doc(root, sources, entities):
    page = {"id": "PAGE-1", "route": "/policies", "name": "p", "requirements": [], "users": [], "data": {}}
    return {"data": {"entities": entities}, "workflows": [], "requirements": [], "roles": [], "widgets": [],
            "pages": [page], "pageLayouts": [{"page": "PAGE-1", "root": root, "dataSources": sources}]}


SEARCH = {"type": "Stack", "props": {}, "children": [{"type": "Input", "props": {"type": "search", "name": "q", "placeholder": "Search"}, "children": []}]}
POLICY = {"id": "ENTITY-005", "name": "Policy", "fields": [{"name": "id", "type": "uuid", "primaryKey": True}, {"name": "title", "type": "text"}]}
COUNTER = {"id": "ENTITY-006", "name": "Counter", "fields": [{"name": "id", "type": "uuid", "primaryKey": True}, {"name": "count", "type": "integer"}]}


def test_a_search_box_with_a_list_of_text_is_fine():
    doc = _doc(SEARCH, [{"name": "policies", "op": "list", "entity": "Policy"}], [POLICY])
    assert not [f for f in functional_findings(doc) if f["rule"].startswith("search-")]


def test_a_search_box_on_a_page_with_no_list_is_refused():
    doc = _doc(SEARCH, [], [POLICY])
    rules = [(f["rule"], f["detail"]) for f in functional_findings(doc)]
    assert any(r == "search-without-source" and "no list source" in d for r, d in rules), rules


def test_a_search_over_an_entity_with_no_text_says_which_fields_it_has():
    doc = _doc(SEARCH, [{"name": "counters", "op": "list", "entity": "Counter"}], [COUNTER])
    rules = [(f["rule"], f["detail"]) for f in functional_findings(doc)]
    assert any(r == "search-without-columns" and "Counter" in d and "count" in d for r, d in rules), rules
