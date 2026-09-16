"""ED-14, the half a file removal cannot do. On a Blueprint-built app the
schema and nav-flow entry the editor deletes are PROJECTED on every build; the
page must be retired in the Blueprint too, or the next Verify & Fix brings it
back. DEPRECATED is the contract's own retirement status, and every reader
that matters already skips it."""

import json

import pytest

from services.blueprint.functional_completeness import page_findings
from services.blueprint.orchestrator import DAG, subjects_for
from services.blueprint.page_planner import plan_pages
from services.blueprint.projection import project_nav_flow
from services.blueprint.service import BlueprintService
from pathlib import Path

from services.remove_page_seam import retire_blueprint_pages


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Offers", domain="sales")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Offer", "table": "offers",
                                   "fields": [{"name": "id", "type": "uuid"}, {"name": "title", "type": "string"}]}]}
    s.doc["pages"] = [
        {"id": "PAGE-001", "name": "Offers", "route": "/offers", "pattern": "entity_list", "purpose": "List.",
         "actions": ["view"], "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-002", "name": "Offer", "route": "/offers/[id]", "pattern": "record_workspace", "purpose": "One.",
         "actions": ["view"], "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-003", "name": "New offer", "route": "/offers/new", "pattern": "form", "purpose": "Add.",
         "actions": ["create"], "data": {"primaryEntity": "ENTITY-001"}},
    ]
    s.doc["pageLayouts"] = [
        {"page": pid, "root": {"type": "Stack", "props": {}, "children": []}, "dataSources": []}
        for pid in ("PAGE-001", "PAGE-002", "PAGE-003")]
    s.save()
    return s


def _statuses(root):
    doc = BlueprintService.load(output_dir=root).doc
    return {p["id"]: p.get("status") for p in doc["pages"]}, \
           {l["page"]: l.get("status") for l in doc["pageLayouts"]}


def test_the_page_and_its_layout_are_retired_and_nothing_projects_them_again(svc):
    assert retire_blueprint_pages(svc.output_dir, "/offers") == ["PAGE-001"]
    pages, layouts = _statuses(svc.output_dir)
    assert pages == {"PAGE-001": "DEPRECATED", "PAGE-002": None, "PAGE-003": None}   # the others untouched
    assert layouts["PAGE-001"] == "DEPRECATED" and layouts["PAGE-002"] is None
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    assert next(p for p in doc["pages"] if p["id"] == "PAGE-001")["syncNote"] == "removed from the app in the editor"
    # never composed again, never written again, not in nav-flow, not a defect
    assert subjects_for(DAG["page_layouts"], doc) == ["PAGE-002", "PAGE-003"]
    assert set(plan_pages(doc)["planned"]) == {"PAGE-002", "PAGE-003"}
    app = Path(svc.output_dir) / "app"
    project_nav_flow(doc, app)
    nav = json.loads((app / "src" / "contracts" / "nav-flow.json").read_text())
    assert "/offers" not in {p.get("route") for p in nav.get("pages") or []}
    assert [f for f in page_findings(doc) if f["page"] == "PAGE-001"] == []


def test_cascade_retires_the_feature_area_and_a_second_call_is_idempotent(svc):
    assert retire_blueprint_pages(svc.output_dir, "/offers", cascade=True) == ["PAGE-001", "PAGE-002", "PAGE-003"]
    assert retire_blueprint_pages(svc.output_dir, "/offers", cascade=True) == []
    assert retire_blueprint_pages(svc.output_dir, "/nowhere") == []


def test_a_tree_without_a_blueprint_is_left_to_the_files(tmp_path):
    assert retire_blueprint_pages(tmp_path, "/offers") == []


def test_the_completion_line_does_not_count_a_retired_page(svc):
    from routers.blueprint_generate import _build_complete_message
    retire_blueprint_pages(svc.output_dir, "/offers/new")
    doc = BlueprintService.load(output_dir=svc.output_dir).doc
    assert "2 pages ready" in (_build_complete_message(doc) or "")
