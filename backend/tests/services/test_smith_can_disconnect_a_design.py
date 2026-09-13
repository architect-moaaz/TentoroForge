"""Smith undoes a design connection in one move, and the change is the Blueprint's.

The first time a connected design had to go (Criterion Refunds v2, 2026-09-13:
fifteen frames bound to fifteen pages in file order, every page one text node)
it took a script against the Blueprint files, because `figmaFrame` is a pinned
page field no proposal may remove and no verb existed. Now the words
"disconnect the design" are a verb: the source goes, no page names a frame,
the drawn layouts are retired, the version records it, and the plan that
follows composes the pages — nothing upstream of them.
"""
import json
from pathlib import Path

from services.blueprint.service import BlueprintService
from services.smith import design_disconnect as D
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP
from services.smith.understand_ask import _PROMPT


def _svc(tmp_path):
    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="t", name="T",
                                  domain="unknown", description="a case tracker")
    svc.doc["designSources"] = [{"id": "FIGMA-001", "type": "figma", "fileKey": "k",
                                 "url": "https://www.figma.com/design/k/x", "name": "x",
                                 "treatAs": "evidence", "frames": [{"nodeId": "1:2", "name": "F"}]}]
    svc.doc["pages"] = [
        {"id": "PAGE-001", "name": "Dashboard", "route": "/dashboard", "pattern": "dashboard",
         "purpose": "home", "access": "authenticated", "figmaFrame": "1:2", "status": "PROPOSED"},
        {"id": "PAGE-002", "name": "Cases", "route": "/cases", "pattern": "entity_list",
         "purpose": "list", "access": "authenticated", "status": "PROPOSED"},
    ]
    svc.doc["pageLayouts"] = [
        {"page": "PAGE-001", "composedBy": "figma", "root": {"type": "Text", "props": {"content": "x"}, "children": []}, "dataSources": []},
        {"page": "PAGE-002", "composedBy": "a2ui", "root": {"type": "Stack", "props": {}, "children": []}, "dataSources": []},
    ]
    svc.save()
    return svc


def test_the_verb_exists_and_needs_nothing():
    assert REQUIRED_BY_VERB["disconnect_design"] == set()
    assert "component library" in VERB_HELP["disconnect_design"]
    assert "disconnect_design" in _PROMPT


def test_disconnect_removes_the_source_the_frames_and_the_drawn_layouts(tmp_path):
    svc = _svc(tmp_path)
    before = svc.doc["version"]
    out = D.disconnect(svc, "disconnect the Figma design")
    assert out["applied"] and out["sources"] == ["FIGMA-001"]
    assert out["unbound"] == ["PAGE-001"] and out["dropped_layouts"] == 1
    assert svc.doc["designSources"] == []
    assert not any(p.get("figmaFrame") for p in svc.doc["pages"])
    assert [l["page"] for l in svc.doc["pageLayouts"]] == ["PAGE-002"]
    assert svc.doc["version"] == before + 1


def test_the_change_is_in_the_history_with_its_reason(tmp_path):
    svc = _svc(tmp_path)
    D.disconnect(svc, "disconnect the Figma design")
    last = svc.doc["changeHistory"][-1]
    assert last["userRequest"] == "disconnect the Figma design"
    assert "component library" in last["smithInterpretation"]
    current = json.loads((Path(tmp_path) / ".forge" / "blueprint" / "current.json").read_text())
    assert current["designSources"] == []


def test_the_plan_composes_the_pages_and_nothing_upstream_of_them():
    plan = D.recomposition_plan()
    assert plan[0] == "page_layouts"
    assert "verification" in plan
    assert not {"page_contracts", "page_details", "workflows", "data_model"} & set(plan)


def test_nothing_connected_is_a_no_op(tmp_path):
    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="t", name="T",
                                  domain="unknown", description="a case tracker")
    v = svc.doc["version"]
    out = D.disconnect(svc, "disconnect the design")
    assert out == {"applied": False, "reason": "no design is connected to this application"}
    assert svc.doc["version"] == v
