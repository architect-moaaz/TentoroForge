"""R1/R3/R4 from the re-test: CRLF files stay CRLF, every way a step reads an
input counts as a read, and link lists of known components are checked."""
import json

from services.choice_control_guard import ensure_choices_are_controls
from services.control_inputs_guard import ensure_controls_supply_inputs
from services.link_target_guard import ensure_links_resolve


def _crlf(obj) -> bytes:
    return (json.dumps(obj, indent=2) + "\n").replace("\n", "\r\n").encode()


def _put(tmp_path, rel, obj):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_crlf(obj))
    return p


def _assert_crlf_only(p):
    b = p.read_bytes()
    assert b.count(b"\r\n") == b.count(b"\n") and b.count(b"\n") > 3


def test_a_crlf_page_stays_crlf_when_a_dead_link_is_removed(tmp_path):
    p = _put(tmp_path, "src/schemas/home.json", {"route": "/", "root": {"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "Gone", "navigate": "/nowhere"}},
        {"type": "Text", "props": {"content": "keep me"}}]}})
    before = p.read_bytes().count(b"\r\n")
    ensure_links_resolve(str(tmp_path))
    assert b"nowhere" not in p.read_bytes()
    _assert_crlf_only(p)
    assert p.read_bytes().count(b"\r\n") <= before


def test_a_crlf_workflow_and_choice_page_stay_crlf(tmp_path):
    wf = _put(tmp_path, "src/lib/workflows/definitions/m.json",
              {"id": "f", "name": "Mark Read", "requiredInputs": ["userId"], "definition": {"v": "{{userId}}"}})
    _put(tmp_path, "src/schemas/a.json", {"route": "/a", "root": {"type": "Button", "props": {"label": "Mark all", "workflow": "f"}}})
    ensure_controls_supply_inputs(str(tmp_path))
    assert b"{{user.id}}" in wf.read_bytes()
    _assert_crlf_only(wf)
    page = _put(tmp_path, "src/schemas/order.json", {"route": "/order", "root": {"type": "Stack", "children": [
        {"type": "Row", "children": [{"type": "Button", "props": {"label": "Dine-in"}}, {"type": "Button", "props": {"label": "Delivery"}}]},
        {"type": "Form", "props": {"workflow": "F", "fields": [{"kind": "text", "name": "tableNumber", "label": "Table"}]}}]}})
    assert ensure_choices_are_controls(str(tmp_path))["converted"]
    _assert_crlf_only(page)


def _wf_reading(tmp_path, ref):
    wf = _put(tmp_path, "src/lib/workflows/definitions/n.json",
              {"id": "f", "name": "Add Note", "requiredInputs": ["note"], "definition": {"values": {"body": ref}}})
    _put(tmp_path, "src/schemas/a.json", {"route": "/a", "root": {"type": "Button", "props": {"label": "Go", "workflow": "f"}}})
    return wf


def test_every_way_a_step_reads_an_input_counts_as_a_read(tmp_path):
    for ref in ("{{inputs.note}}", "{{trigger.note}}", "${input.note}", "{{input.note}}"):
        wf = _wf_reading(tmp_path, ref)
        r = ensure_controls_supply_inputs(str(tmp_path))
        assert r["repaired"] == [] and [f["input"] for f in r["findings"]] == ["note"], ref
        assert json.loads(wf.read_text())["requiredInputs"] == ["note"], ref


def test_dead_links_in_a_breadcrumb_are_checked_but_data_rows_are_not(tmp_path):
    p = _put(tmp_path, "src/schemas/home.json", {"route": "/", "root": {"type": "Stack", "children": [
        {"type": "Breadcrumb", "props": {"items": [{"label": "Products", "href": "/products"}, {"label": "Here"}]}},
        {"type": "Table", "props": {"items": [{"label": "x", "href": "/zzz"}]}}]}})
    r = ensure_links_resolve(str(tmp_path))
    assert [x["target"] for x in r["removed"]] == ["/products"]
    assert "/zzz" in p.read_text()
