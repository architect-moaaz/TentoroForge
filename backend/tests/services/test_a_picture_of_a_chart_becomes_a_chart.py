"""A flattened design is understood by looking at it, then wired to the data.

WHY LOOKING IS THE ONLY OPTION. The dashboard this was built against carries no
names: all 274 `data-name` attributes are `Vector`, `Group`, `Clip path group`
or `Mask group`, and Figma's own metadata says `Group 3` and
`clip2_568_17068`. Two text nodes in 626 have real words. So
`figma_binding_extractor`'s name-match and semantic-type detectors have nothing
to read, and no parser will ever find the chart.

What survives flattening is the picture, and a bar chart still looks like one.
The pipeline is therefore: `regions` measures the rectangles, `vision` says
what each one is AND what it should show, `realize` swaps the confident ones
for live components. On the real frame that produced six Charts and one Table
bound to `Record` and `MetricSnapshot`, with source names — `totalProductSales`,
`requestsCreated` — derived from titles the model read off the drawing, which
is the only naming the file has anywhere.

THE FAILURE THAT MATTERS IS THE CONFIDENT WRONG ONE. Replacing a correct
picture with a wrong component removes something right and makes the mistake
look deliberate. So every gate here fails toward keeping the drawing: an
unknown kind, a missing entity, an invented field, a low confidence, a
classification for a region that is not in the tree. An unreplaced region is
the normal outcome, not an error.
"""
import json

import pytest

from services.figma.realize import realize
from services.figma.regions import candidates, regions
from services.figma.vision import classify

W, H = 4000.0, 2000.0

CODE = '''
<div className="bg-white relative size-full" data-node-id="1:1">
  <div className="absolute contents left-[10px] top-[10px]">
    <div className="absolute inset-[10%_50%_50%_10%]" data-node-id="1:10">
      <img className="absolute block inset-0 size-full" src={a} alt="" />
    </div>
    <div className="absolute inset-[10%_10%_50%_60%]" data-node-id="1:20">
      <img className="absolute block inset-0 size-full" src={b} alt="" />
    </div>
    <div className="absolute inset-[49%_49%_49%_49%]" data-node-id="1:30">
      <img className="absolute block inset-0 size-full" src={c} alt="" />
    </div>
  </div>
</div>
'''

ENTITIES = [{
    "name": "Record",
    "fields": [{"name": "id"}, {"name": "category"}, {"name": "amount"},
               {"name": "occurredAt"}, {"name": "status"}],
}]


def _tree(*node_ids):
    """A composed tree whose cards still carry their Figma provenance."""
    return {
        "type": "Container", "props": {}, "children": [
            {"type": "Container", "props": {"_figmaNodeId": nid},
             "children": [{"type": "Image", "props": {"src": f"/figma/{nid}.svg",
                                                      "alt": ""}}]}
            for nid in node_ids
        ],
    }


# ------------------------------------------------------------------ measuring

def test_every_positioned_card_is_found_with_its_id():
    found = {r.node_id for r in regions(CODE, W, H)}
    assert found == {"1:10", "1:20", "1:30"}


def test_a_rectangle_is_in_frame_pixels():
    """Percentages resolve against the frame because the `contents` wrappers
    between have no box — which is why `jsx_to_schema` dissolves them."""
    card = next(r for r in regions(CODE, W, H) if r.node_id == "1:10")
    assert card.x == pytest.approx(400.0)      # left 10% of 4000
    assert card.y == pytest.approx(200.0)      # top 10% of 2000
    assert card.width == pytest.approx(1600.0)  # 100 - 10 - 50
    assert card.height == pytest.approx(800.0)  # 100 - 10 - 50


def test_the_biggest_rectangles_come_first():
    """A caller that can only afford to look at twenty things should look at
    the twenty biggest — a dashboard's charts are its big rectangles."""
    areas = [r.area for r in regions(CODE, W, H)]
    assert areas == sorted(areas, reverse=True)


def test_an_icon_sized_rectangle_is_not_a_candidate():
    """1:30 is 2% of each axis — 80x40px. Looking at it costs a screenshot and
    a share of a vision call and can never yield a chart."""
    assert "1:30" not in {r.node_id for r in candidates(CODE, W, H)}


def test_a_frame_with_no_size_yields_nothing():
    assert regions(CODE, 0, 0) == []


# ----------------------------------------------------------------- classifying

def _ask(payload):
    """A fake model. `ModelClient` documents that a bare str is a legal reply,
    which is what keeps this a one-liner."""
    return lambda **_kw: json.dumps(payload)


def _shots(*node_ids):
    return [(r, f"/tmp/{r.node_id}.png")
            for r in regions(CODE, W, H) if r.node_id in node_ids]


def test_a_classification_is_kept_with_its_binding():
    out = classify(_ask({"regions": [{
        "nodeId": "1:10", "kind": "bar_chart", "title": "Revenue",
        "confidence": 0.9, "reason": "bars", "entity": "Record",
        "xField": "category", "valueField": "amount"}]}),
        _shots("1:10"), ENTITIES)
    assert out[0]["kind"] == "bar_chart"
    assert (out[0]["entity"], out[0]["xField"], out[0]["valueField"]) == \
        ("Record", "category", "amount")


def test_a_field_the_entity_does_not_have_is_dropped():
    """A binding to a missing column renders an empty chart, which reads as a
    data outage rather than a bad guess."""
    out = classify(_ask({"regions": [{
        "nodeId": "1:10", "kind": "bar_chart", "confidence": 0.9,
        "reason": "bars", "entity": "Record",
        "xField": "notAField", "valueField": "amount"}]}),
        _shots("1:10"), ENTITIES)
    assert out[0]["xField"] == ""
    assert out[0]["valueField"] == "amount"


def test_an_entity_that_does_not_exist_is_dropped():
    out = classify(_ask({"regions": [{
        "nodeId": "1:10", "kind": "table", "confidence": 0.9, "reason": "grid",
        "entity": "Invented", "columns": ["name"]}]}), _shots("1:10"), ENTITIES)
    assert out[0]["entity"] == ""


def test_a_region_the_model_invented_is_discarded():
    """Evidence that refers to nothing is not evidence."""
    assert classify(_ask({"regions": [{
        "nodeId": "9:99", "kind": "table", "confidence": 1.0, "reason": "x"}]}),
        _shots("1:10"), ENTITIES) == []


def test_a_model_failure_costs_only_the_enrichment():
    def boom(**_kw):
        raise RuntimeError("no")
    assert classify(boom, _shots("1:10"), ENTITIES) == []


# ------------------------------------------------------------------ realizing

CHART = {"nodeId": "1:10", "kind": "bar_chart", "title": "Total Product Sales",
         "confidence": 0.93, "reason": "bars", "entity": "Record",
         "xField": "category", "valueField": "amount", "columns": []}
TABLE = {"nodeId": "1:20", "kind": "table", "title": "Companies",
         "confidence": 0.96, "reason": "grid", "entity": "Record",
         "xField": "", "valueField": "", "columns": ["name", "status"]}


def test_a_picture_becomes_a_chart_bound_to_a_source():
    root, sources, applied = realize(_tree("1:10"), [CHART])
    node = root["children"][0]
    assert node["type"] == "Chart"
    assert node["props"]["chartType"] == "bar"
    assert node["props"]["data"] == "{{totalProductSales}}"
    assert sources == [{"name": "totalProductSales", "op": "series",
                        "entity": "Record", "groupBy": "category",
                        "agg": {"fn": "sum", "field": "amount"}}]
    assert applied[0]["title"] == "Total Product Sales"


def test_a_picture_becomes_a_table_with_readable_headers():
    root, sources, _ = realize(_tree("1:20"), [TABLE])
    node = root["children"][0]
    assert node["type"] == "Table"
    assert node["props"]["columns"] == [{"key": "name", "label": "Name"},
                                        {"key": "status", "label": "Status"}]
    assert sources[0]["op"] == "list"


def test_the_source_name_comes_from_the_title_on_the_drawing():
    """The only human name this design has is the one printed inside it."""
    _root, sources, _ = realize(_tree("1:10"), [CHART])
    assert sources[0]["name"] == "totalProductSales"


def test_two_regions_with_one_title_do_not_collide():
    """A real frame produced three identically-sized wrappers for one table."""
    second = {**CHART, "nodeId": "1:20"}
    _root, sources, _ = realize(_tree("1:10", "1:20"), [CHART, second])
    assert len({s["name"] for s in sources}) == 2


# ------------------------------------------------- every gate keeps the drawing

@pytest.mark.parametrize("entry,why", [
    ({**CHART, "confidence": 0.3}, "unconfident"),
    ({**CHART, "entity": ""}, "unbound"),
    ({**CHART, "xField": ""}, "nothing to group by"),
    ({**TABLE, "columns": []}, "no columns to show"),
    ({**CHART, "kind": "unknown"}, "unrecognised"),
    ({**CHART, "kind": "logo"}, "not actionable"),
])
def test_an_unusable_verdict_leaves_the_image_alone(entry, why):
    root, sources, applied = realize(_tree(entry["nodeId"]), [entry])
    assert root["children"][0]["type"] == "Container", why
    assert sources == [] and applied == []


def test_a_classification_for_a_missing_node_declares_no_source():
    """A source nobody reads binds nothing and would show as a phantom fetch."""
    _root, sources, applied = realize(_tree("9:99"), [CHART])
    assert sources == [] and applied == []


def test_nothing_classified_is_the_tree_unchanged():
    tree = _tree("1:10")
    root, sources, applied = realize(tree, [])
    assert root is tree and sources == [] and applied == []
