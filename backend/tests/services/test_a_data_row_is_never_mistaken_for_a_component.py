"""R5/R6: a record with a `type` column is data, not a component; link lists of
nav-style components are checked by component name."""
import json

from services.choice_control_guard import ensure_choices_are_controls
from services.control_inputs_guard import ensure_controls_supply_inputs
from services.link_target_guard import ensure_links_resolve

NOTHING = {"created": [], "repointed": [], "removed": [], "findings": []}


def _page(tmp_path, root, rel="home.json"):
    p = tmp_path / "src/schemas" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"route": "/", "root": root}, indent=2) + "\n")
    return p


def test_a_table_row_with_a_type_column_is_left_alone(tmp_path):
    p = _page(tmp_path, {"type": "Table", "props": {"rows": [{"type": "A", "href": "/ghost"}]}})
    before = p.read_text()
    assert ensure_links_resolve(str(tmp_path)) == NOTHING
    assert p.read_text() == before


def test_rows_that_look_like_buttons_or_sit_in_lists_are_left_alone(tmp_path):
    p = _page(tmp_path, {"type": "Stack", "children": [
        {"type": "Table", "props": {"rows": [{"type": "Button", "navigate": "/ghost"}]}},
        {"type": "List", "props": {"items": [{"type": "Link", "href": "/ghost2"}]}},
        {"type": "DataGrid", "props": {"data": [{"type": "x", "to": "/ghost3"}]}},
        {"type": "Chart", "props": {"data": [{"type": "bar", "href": "/ghost4"}]}}]})
    before = p.read_text()
    assert ensure_links_resolve(str(tmp_path)) == NOTHING
    assert p.read_text() == before


def test_a_dead_link_in_tabs_and_navbar_lists_is_still_removed(tmp_path):
    p = _page(tmp_path, {"type": "Stack", "children": [
        {"type": "Tabs", "props": {"tabs": [{"label": "A", "href": "/dead-tab"}]}},
        {"type": "NavBar", "props": {"links": [{"label": "B", "href": "/dead-nav"}]}},
        {"type": "Pagination", "props": {"items": [{"label": "1", "href": "/dead-page"}]}}]})
    r = ensure_links_resolve(str(tmp_path))
    assert {x["target"] for x in r["removed"]} == {"/dead-tab", "/dead-nav", "/dead-page"}
    assert "dead-" not in p.read_text()


def test_a_data_row_that_looks_like_a_button_is_not_a_control_or_a_choice(tmp_path):
    rows = [{"type": "Button", "props": {"label": "Dine-in", "workflow": "W"}},
            {"type": "Button", "props": {"label": "Delivery"}}, {"type": "Button", "props": {"label": "Pickup"}}]
    p = _page(tmp_path, {"type": "Stack", "children": [
        {"type": "Table", "props": {"rows": rows}},
        {"type": "Form", "props": {"workflow": "F", "fields": [{"kind": "text", "name": "t", "label": "T"}]}}]})
    wf = tmp_path / "src/lib/workflows/definitions/w.json"
    wf.parent.mkdir(parents=True)
    wf.write_text(json.dumps({"id": "W", "name": "W", "requiredInputs": ["x"], "definition": {"v": "{{x}}"}}))
    before, wbefore = p.read_text(), wf.read_text()
    assert ensure_choices_are_controls(str(tmp_path)) == {"converted": [], "findings": []}
    assert ensure_controls_supply_inputs(str(tmp_path))["findings"] == []
    assert p.read_text() == before and wf.read_text() == wbefore
