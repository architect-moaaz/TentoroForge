"""What the translation removes is written down, and what matters refuses.

`a2ui_to_forge` maintained six diagnostic channels — `warnings`,
`assumptions`, `unresolved`, `dangling`, `dropped_data_model_keys`,
`dominant_entity` — built them at real cost, and every caller dropped all but
one on the floor. The losses with no channel at all were the expensive ones:

  * a payload whose root never resolved was replaced by an EMPTY STACK, and
    the floor then refused the page for having no table, no KPIs, no anything
    — a symptom reported as a cause;
  * every unreferenced component the composer wrote was dropped with no
    record anywhere, so a page that lost its table was refused for having no
    list surface;
  * `optionsFrom` was popped off a form field and, when its source could not
    be resolved, never put back and the enum recovery skipped — a select with
    neither options nor a source, which the contract refuses;
  * `bind` was excused from the unknown-prop report as "early" and then never
    lifted, so it met a strict node as an unknown key and failed the whole
    page parse with nothing naming it.

One ledger now, and the caller reads it. Material losses refuse the page so
the composer is asked again and told the cause; immaterial ones are recorded
and pass.
"""
import pytest

from services.a2ui_to_forge import Losses, translate


def _payload(components, data_model=None):
    messages = []
    if data_model is not None:
        messages.append({"updateDataModel": {"value": data_model}})
    messages.append({"updateComponents": {"components": components}})
    return {"messages": messages}


REGISTRY = {"entities": []}


def test_the_ledger_separates_what_a_reader_would_notice():
    lost = Losses()
    lost.record("renamed", "b1", "label", "the component calls it content")
    lost.record("orphaned_component", "t1", "Table", "nothing points at it",
                material=True)
    assert len(lost) == 2
    assert [e["what"] for e in lost.material()] == ["Table"]
    assert "Table" in lost.summary()
    assert "label" not in lost.summary()


def test_a_page_that_never_translated_says_so():
    """It used to become an empty Stack, and the floor reported the silence."""
    out = translate(_payload([{"id": "card", "component": "Card"}]), REGISTRY)
    kinds = {e["kind"] for e in out["material_losses"]}
    assert "dropped_page" in kinds
    said = next(e for e in out["losses"] if e["kind"] == "dropped_page")
    assert "root" in said["detail"]


def test_a_component_nothing_points_at_is_reported_not_swallowed():
    out = translate(_payload([
        {"id": "root", "component": "Stack", "children": ["heading"]},
        {"id": "heading", "component": "Heading", "content": "Nurses"},
        {"id": "table", "component": "Table"},
    ]), REGISTRY)
    orphans = [e for e in out["losses"] if e["kind"] == "orphaned_component"]
    assert [e["where"] for e in orphans] == ["table"]
    assert orphans[0]["material"] is True


def test_a_template_is_referenced_even_though_it_is_never_placed():
    """A repeat template is named once, by `componentId`, and expanded into
    instances carrying none of its id. A check keyed on placement called every
    one of them an orphan and refused the page."""
    out = translate(_payload([
        {"id": "root", "component": "Stack", "children": ["tiles"]},
        {"id": "tiles", "component": "Row",
         "children": {"componentId": "tile", "path": "/kpis"}},
        {"id": "tile", "component": "MetricTile", "format": "number",
         "label": {"path": "label"}, "value": {"path": "value"}},
    ], {"kpis": [{"label": "Total", "value": "12"}]}), REGISTRY)
    orphans = [e["where"] for e in out["losses"]
               if e["kind"] == "orphaned_component"]
    assert orphans == []


def test_a_bind_prop_is_lifted_beside_the_node_not_left_among_the_props():
    out = translate(_payload([
        {"id": "root", "component": "Stack", "children": ["t"]},
        {"id": "t", "component": "Text", "content": "hi", "bind": "/x/y"},
    ]), REGISTRY)
    text = out["schema"]["root"]["children"][0]
    assert text["bind"] == "/x/y"
    assert "bind" not in text["props"]


def test_an_ordinary_page_loses_nothing_material():
    out = translate(_payload([
        {"id": "root", "component": "Stack", "children": ["h", "b"]},
        {"id": "h", "component": "Heading", "content": "Nurses"},
        {"id": "b", "component": "Button", "label": "Add"},
    ]), REGISTRY)
    assert out["material_losses"] == []


def test_every_loss_carries_enough_to_act_on():
    out = translate(_payload([
        {"id": "root", "component": "Stack", "children": ["h"]},
        {"id": "h", "component": "Heading", "content": "Nurses"},
        {"id": "stray", "component": "Chart"},
    ]), REGISTRY)
    for entry in out["losses"]:
        assert entry["kind"] and entry["detail"]
        assert set(entry) == {"kind", "where", "what", "detail", "material"}


BILL_REGISTRY = {"entities": {"Bill": {"table": "bills", "columns": [
    {"name": "id", "type": "uuid"}, {"name": "title", "type": "text"}]}}}


def test_a_required_prop_is_caught_wherever_it_was_lost():
    """Seven places can drop a prop and exactly one asked whether it was
    required. Asked once at the end instead, about what actually survived."""
    out = translate(_payload([
        {"id": "root", "component": "Stack", "children": ["chart"]},
        {"id": "chart", "component": "Chart", "chartType": "bar",
         "title": "Bills", "data": {"path": "/bill/rows"}},
    ]), BILL_REGISTRY)
    lost = {(e["where"], e["what"]) for e in out["material_losses"]}
    assert ("chart", "data") in lost


def test_the_specific_reason_is_reported_once_not_twice():
    """A site that said why is more use than 'it did not survive', and both
    in the summary is the same loss reported twice."""
    out = translate(_payload([
        {"id": "root", "component": "Stack", "children": ["chart"]},
        {"id": "chart", "component": "Chart", "chartType": "bar",
         "title": "Bills", "data": {"path": "/bill/rows"}},
    ]), BILL_REGISTRY)
    for_data = [e for e in out["losses"] if e["what"] == "data"]
    assert len(for_data) == 1
    assert "groupable" in for_data[0]["detail"]


def test_a_prop_the_binder_supplies_itself_is_not_reported_lost():
    """`Chart.series` is required, the binder drops what the composer wrote
    and re-attaches its own. Nothing was lost and nothing should be claimed."""
    registry = {"entities": {"Bill": {"table": "bills", "columns": [
        {"name": "id", "type": "uuid"},
        {"name": "status", "type": "varchar", "enum": ["draft", "done"]}]}}}
    out = translate(_payload([
        {"id": "root", "component": "Stack", "children": ["chart"]},
        {"id": "chart", "component": "Chart", "chartType": "bar",
         "title": "Bills by Stage", "data": {"path": "/chart/data"},
         "series": [{"name": "Count", "dataKey": "value"}]},
    ], {"chart": {"data": [{"label": "draft", "value": 3}]}}), registry)
    assert out["material_losses"] == []
    chart = out["schema"]["root"]["children"][0]
    assert "series" in chart["props"]


def test_the_composer_is_refused_with_the_cause_not_the_symptom(tmp_path):
    """The whole point of reading the ledger: a page that lost its list
    surface in translation is refused for losing it, not for lacking it."""
    from services.a2ui_authority import compose_page_via_a2ui

    (tmp_path / "app" / "src" / "contracts").mkdir(parents=True)
    payload = _payload([
        {"id": "root", "component": "Stack", "children": ["h"]},
        {"id": "h", "component": "Heading", "content": "Nurses"},
        {"id": "table", "component": "Table"},
    ])
    registry = {"entities": {"Nurse": {"table": "nurses", "columns": [
        {"name": "id", "type": "uuid"}, {"name": "name", "type": "varchar"}]}}}
    out = compose_page_via_a2ui(
        str(tmp_path / "app"), "/nurses", "entity_list",
        surface_provider=lambda *_a, **_kw: payload,
        registry=registry,
    )
    assert out["applied"] is False
    assert "did not survive translation" in out["reason"]
    assert "Table" in out["reason"]
    assert out["losses"]
