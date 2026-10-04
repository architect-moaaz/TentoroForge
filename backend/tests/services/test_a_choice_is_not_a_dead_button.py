"""Either/or choices: inert sibling buttons become a form choice; the page
probe reads a choice by its selected state, and a dead button stays dead."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint.page_review import hard_findings
from services.choice_control_guard import ensure_choices_are_controls

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _page(tmp_path, root):
    p = tmp_path / "src/schemas/order.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"route": "/order", "root": root}))
    return p


def _btn(label, **props):
    return {"type": "Button", "props": {"label": label, **props}}


def _order_page(buttons):
    return {"type": "Stack", "children": [
        {"type": "Row", "children": buttons},
        {"type": "Form", "props": {"workflow": "FLOW-1", "fields": [
            {"kind": "text", "name": "tableNumber", "label": "Table number"},
            {"kind": "text", "name": "deliveryAddress", "label": "Delivery address"},
            {"kind": "text", "name": "notes", "label": "Notes"}]}}]}


def test_inert_sibling_buttons_become_a_bound_choice(tmp_path):
    p = _page(tmp_path, _order_page([_btn("Dine-in"), _btn("Delivery")]))
    r = ensure_choices_are_controls(str(tmp_path))
    assert [c["options"] for c in r["converted"]] == [["Dine-in", "Delivery"]]
    root = json.loads(p.read_text())["root"]
    assert [c["type"] for c in root["children"]] == ["Form"]          # the dead buttons and their empty Row are gone
    fields = {f["name"]: f for f in root["children"][0]["props"]["fields"]}
    choice = root["children"][0]["props"]["fields"][0]
    assert choice["kind"] == "choice" and [o["value"] for o in choice["options"]] == ["dine_in", "delivery"]
    assert fields["tableNumber"]["interaction"]["visibleIf"] == "orderType == 'dine_in'"
    assert fields["deliveryAddress"]["interaction"]["visibleIf"] == "orderType == 'delivery'"
    assert "interaction" not in fields["notes"]


def test_buttons_that_do_something_and_a_lone_button_are_left_alone(tmp_path):
    p = _page(tmp_path, _order_page([_btn("Dine-in", navigate="/a"), _btn("Delivery", workflow="W")]))
    before = p.read_text()
    assert ensure_choices_are_controls(str(tmp_path)) == {"converted": [], "findings": []}
    assert p.read_text() == before


def test_with_no_form_to_hold_it_the_choice_is_a_named_finding(tmp_path):
    p = _page(tmp_path, {"type": "Row", "children": [_btn("Dine-in"), _btn("Delivery")]})
    before = p.read_text()
    r = ensure_choices_are_controls(str(tmp_path))
    assert r["findings"] == [{"page": "order.json", "buttons": ["Dine-in", "Delivery"]}]
    assert p.read_text() == before


def test_rerun_is_idempotent(tmp_path):
    p = _page(tmp_path, _order_page([_btn("Dine-in"), _btn("Delivery")]))
    ensure_choices_are_controls(str(tmp_path))
    after = p.read_text()
    assert ensure_choices_are_controls(str(tmp_path)) == {"converted": [], "findings": []}
    assert p.read_text() == after


def test_the_verdict_still_names_a_dead_button_but_not_a_choice():
    dead = {"controls": [{"kind": "button", "label": "Dine-in", "outcome": "nothing", "detail": "x"}]}
    alive = {"controls": [{"kind": "button", "label": "Dine-in", "outcome": "chose", "detail": "x"}]}
    assert hard_findings(dead) and not hard_findings(alive)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_probe_judges_a_choice_by_its_selected_state():
    js = f"""
    import {{ judgeQuiet }} from {json.dumps((SCRIPTS / "probe_judge.mjs").as_uri())};
    const b = {{ url: "u", text: "t", dialogs: 0, expanded: 0, toasts: 0, pressed: "Dine-in", fields: 2 }};
    const out = {{
      flipped: judgeQuiet({{ before: b, after: {{ ...b, pressed: "Delivery" }}, choice: true }}),
      revealed: judgeQuiet({{ before: b, after: {{ ...b, fields: 3 }}, choice: true }}),
      again: judgeQuiet({{ before: b, after: b, choice: true, wasSelected: true, siblings: 1 }}),
      stuck: judgeQuiet({{ before: b, after: b, choice: true, wasSelected: true, siblings: 0 }}),
      dead_choice: judgeQuiet({{ before: b, after: b, choice: true, wasSelected: false }}),
      dead_button: judgeQuiet({{ before: b, after: b }}),
      page_change: judgeQuiet({{ before: b, after: {{ ...b, text: "t2" }} }}),
    }};
    console.log(JSON.stringify(Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.outcome]))));
    """
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
    assert json.loads(r.stdout) == {"flipped": "chose", "revealed": "chose", "again": "chose",
                                    "stuck": "nothing", "dead_choice": "nothing", "dead_button": "nothing",
                                    "page_change": "changed"}
