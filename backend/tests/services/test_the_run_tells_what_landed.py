"""The run says what landed and what the reviewer saw — so the panel can be played.

A subject landed as an id and a colour; what it was lived in the Blueprint
and nowhere a watcher could see. Each subject now lands with a line read off
the document (`landed.summarize_subject`), a page looked at as it was
written is a ledger event with its score and which screenshots exist, the
progress watcher forwards both, the registry keeps them for a page that
loads mid-build, and the screenshots are served by name — never by path.
"""
import json
from pathlib import Path

from services.blueprint.landed import summarize_subject
from services.blueprint.run_ledger import RunLedger
from services.blueprint.run_progress import Progress
from services import run_registry

ROOT = Path(__file__).resolve().parents[2]

DOC = {
    "application": {"name": "Clinic"},
    "roles": [],
    "data": {"entities": [{"id": "ENTITY-001", "name": "Doctor", "fields": [
        {"name": "name"}, {"name": "specialization"}, {"name": "clinic"}, {"name": "email"}, {"name": "status"}]}]},
    "pages": [{"id": "PAGE-001", "name": "Manage Doctors", "route": "/admin/doctors", "pattern": "entity_list",
               "data": {"primaryEntity": "ENTITY-001"}},
              {"id": "PAGE-002", "name": "Doctor", "route": "/admin/doctors/[id]", "feature": "FEAT-1"}],
    "pageCode": [{"page": "PAGE-001", "load": "x" * 1000, "view": "y" * 6500}],
    "workflows": [{"id": "WF-001", "name": "Add doctor", "steps": [{"name": "Create"}, {"name": "Notify"}]}],
    "widgets": [{"id": "W1", "page": "PAGE-001", "label": "Total doctors"}, {"id": "W2", "page": "PAGE-001", "label": "Active"}],
    "designSystem": {"colors": {"primary": "#123456", "accent": "#c2410c"}, "shell": {"chrome": "wide-rail", "tone": "tinted"}},
}


def test_a_subject_lands_as_what_it_is():
    assert summarize_subject(DOC, "entity_fields", "ENTITY-001") == "Doctor — 5 fields: name, specialization, clinic, email +1"
    assert summarize_subject(DOC, "page_details", "PAGE-001") == "Manage Doctors · /admin/doctors — entity_list"
    assert summarize_subject(DOC, "page_code", "PAGE-001") == "Manage Doctors · /admin/doctors — 7k chars of React"
    assert summarize_subject(DOC, "page_details", "FEAT-1~2") == "1 page: /admin/doctors/[id]"
    assert summarize_subject(DOC, "workflow_steps", "WF-001") == "Add doctor — 2 steps: Create, Notify"
    assert summarize_subject(DOC, "analytics", "PAGE-001") == "Manage Doctors — 2 widgets: Total doctors, Active"
    assert summarize_subject(DOC, "data_model", "") == "1 entities: Doctor"
    assert summarize_subject(DOC, "design_system", "") == "primary #123456 · accent #c2410c · wide-rail · tinted"
    assert summarize_subject(DOC, "entity_fields", "ENTITY-404") == ""
    assert summarize_subject(None, "entity_fields", "x") == "", "never raises"


def test_the_ledger_records_the_summary_and_the_look(tmp_path):
    seen = []
    ledger = RunLedger(tmp_path, "r1", observer=seen.append)
    ledger.node_subject("entity_fields", "ENTITY-001", 1, 3, True, "Doctor — 5 fields")
    ledger.node_subject("entity_fields", "ENTITY-002", 2, 3, True)
    ledger.page_look("page_code", "PAGE-001", route="/admin/doctors", attempt=1, score=6, verdict="revise",
                     issues=["no sort affordance", "status dropped on mobile", "c", "d", "e"], broken=0,
                     shots=["desktop", "mobile"])
    subjects = [e for e in seen if e["event"] == "node:subject"]
    assert subjects[0]["summary"] == "Doctor — 5 fields" and "summary" not in subjects[1]
    look = next(e for e in seen if e["event"] == "page:look")
    assert look["route"] == "/admin/doctors" and look["score"] == 6 and look["verdict"] == "revise"
    assert look["issues"] == ["no sort affordance", "status dropped on mobile", "c", "d"], "the first few, not the essay"
    assert look["shots"] == ["desktop", "mobile"] and "image" not in look, "by name, never by bytes"
    lines = [json.loads(l) for l in (tmp_path / ".forge/runs/r1.jsonl").read_text().splitlines()]
    assert any(l["event"] == "page:look" for l in lines)


def test_the_watcher_forwards_both_to_the_panel():
    out = []
    watch = Progress(lambda e, d: out.append((e, d)), total=2)
    watch({"event": "node:subject", "node": "entity_fields", "subject": "ENTITY-001", "index": 1, "total": 3,
           "ok": True, "summary": "Doctor — 5 fields"})
    watch({"event": "page:look", "node": "page_code", "subject": "PAGE-001", "route": "/x", "attempt": 1,
           "score": 8, "verdict": "pass", "issues": [], "broken": 0, "shots": ["desktop"], "at": "now"})
    assert out[0][0] == "node:subject" and out[0][1]["summary"] == "Doctor — 5 fields"
    assert out[1][0] == "page:look" and out[1][1]["score"] == 8 and "at" not in out[1][1]


def test_the_registry_keeps_the_moments_for_a_page_that_loads_late():
    run_registry.begin("proj-x", phase="build")
    run_registry.note("proj-x", "plan", {"nodes": ["a", "b"]})
    run_registry.note("proj-x", "node:subject", {"node": "a", "subject": "S1", "ok": True, "summary": "one", "at": "t"})
    run_registry.note("proj-x", "page:look", {"node": "b", "subject": "P1", "score": 7, "verdict": "revise", "at": "t"})
    run_registry.note("proj-x", "run:heartbeat", {})
    snap = run_registry.snapshot("proj-x")
    assert [m["event"] for m in snap["moments"]] == ["node:subject", "page:look"]
    assert snap["moments"][0]["summary"] == "one" and "at" not in snap["moments"][0]
    for i in range(run_registry.MOMENTS_KEPT + 20):
        run_registry.note("proj-x", "node:subject", {"node": "a", "subject": f"S{i}", "ok": True})
    assert len(run_registry.snapshot("proj-x")["moments"]) == run_registry.MOMENTS_KEPT, "bounded"


def test_the_executor_tells_the_ledger_what_each_look_saw():
    src = (ROOT / "services/blueprint/executors.py").read_text()
    assert 'ledger = getattr(svc, "run_ledger", None)' in src and "ledger.page_look(" in src
    orch = (ROOT / "services/blueprint/orchestrator.py").read_text()
    assert "svc.run_ledger = ledger" in orch and "_landed(svc, key, subject)" in orch


def test_a_look_is_served_by_name_never_by_path():
    src = (ROOT / "routers/blueprint_generate.py").read_text()
    assert '"/api/projects/{project_id}/looks/{page_id}/{attempt}/{name}"' in src
    assert 'name not in ("desktop", "mobile")' in src and 're.fullmatch(r"[A-Za-z0-9_-]+", page_id)' in src
