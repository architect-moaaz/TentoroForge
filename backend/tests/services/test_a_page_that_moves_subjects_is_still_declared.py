"""A page that moves fan-out subjects is still a declared page; a coded page
counts as served; a retired page is not planned.

i3i950po (UAT, 2026-09-25): /doctor, a dashboard with no primary entity, was
its own page_details subject. The content check refused its contract until
it named a primary entity; the retry added one, which moved the page into
that entity's subject; the observer's repair, still for subject PAGE-002,
found nothing declared under it, dropped the page as invented, and — the
reply replacing what stood — retired it. The same build's funnel reported
/login, /signup and /appointments "not served" (coded pages are not in the
schema registry) and counted the retired /doctor as planned.
"""
import json
from pathlib import Path

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.assembly import page_funnel
from services.blueprint.app_sdk import code_page_dir
from services.blueprint.executors import pin_page_identity
from services.blueprint.orchestrator import feature_pages


class _Svc:
    def __init__(self, doc, output_dir):
        self.doc, self.output_dir = doc, str(output_dir)


def test_a_page_that_gained_its_entity_is_repaired_not_retired(tmp_path):
    doc = {
        "data": {"entities": [{"id": "ENTITY-005", "name": "Appointment"}]},
        "pages": [{"id": "PAGE-001", "route": "/appointments", "pattern": "entity_list", "data": {"primaryEntity": "ENTITY-005"}},
                  {"id": "PAGE-002", "route": "/doctor", "pattern": "dashboard", "data": {}}],
    }
    svc = _Svc(doc, tmp_path)
    assert [p["id"] for p in feature_pages(doc, "PAGE-002")] == ["PAGE-002"], "an entity-less page is its own subject"
    # The contract's retry added the entity: the page now belongs to ENTITY-005's subject.
    doc["pages"][1]["data"] = {"primaryEntity": "ENTITY-005"}
    assert feature_pages(doc, "PAGE-002") == []
    result = AgentResult(task_id="t", agent="page_design", confidence=0.9, proposals=[
        ArtifactProposal(section="pages", natural_key="/doctor",
                         body={"id": "PAGE-002", "route": "/doctor", "pattern": "dashboard", "purpose": "The doctor's day"}),
        ArtifactProposal(section="pages", natural_key="/invented",
                         body={"route": "/invented", "pattern": "form", "purpose": "never declared"}),
    ])
    pin_page_identity(svc, "PAGE-002", result)
    assert [p.body["route"] for p in result.proposals] == ["/doctor"], "the moved page is kept; the invented one is not"
    assert result.proposals[0].body["id"] == "PAGE-002"


def test_a_coded_page_is_served_and_a_retired_page_is_not_planned(tmp_path):
    doc = {"pages": [{"id": "PAGE-001", "route": "/appointments", "pattern": "entity_list"},
                     {"id": "PAGE-002", "route": "/doctor", "pattern": "dashboard", "status": "DEPRECATED"},
                     {"id": "PAGE-003", "route": "/login", "pattern": "auth", "access": "public"},
                     {"id": "PAGE-004", "route": "/tasks", "pattern": "entity_list"}],
           "pageCode": [{"page": "PAGE-001", "view": "v", "load": "l"}, {"page": "PAGE-003", "view": "v", "load": "l"},
                        {"page": "PAGE-004", "view": "v", "load": "l"}]}
    app = tmp_path / "app"
    (app / "src/schemas").mkdir(parents=True)
    (app / "src/schemas/registry.ts").write_text('export const schemas = {\n  "/tasks": () => import("./tasks.json"),\n};\n')
    for page in doc["pages"][:1] + doc["pages"][2:3]:            # /appointments and /login are on disk; /tasks is not
        d = app / code_page_dir(page); d.mkdir(parents=True); (d / "view.tsx").write_text("x")
    f = page_funnel(doc, app)
    assert f["missing"] == [], f
    assert f["planned"] == 3 and f["served"] == 3 and f["status"] == "complete"
    (app / code_page_dir(doc["pages"][0]) / "view.tsx").unlink()
    assert page_funnel(doc, app)["missing"] == ["/appointments"], "a coded page whose file is not there is missing"
