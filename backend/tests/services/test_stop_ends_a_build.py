"""Stop ends the work, not only the watching.

The panel's Stop aborted the client's fetch; the build ran on unseen until a
backend restart (forge-v3, 2026-10-10). Now a file beside the ledgers tells
the orchestrator to pause at its next round, the checks to end at their next
page, and either worker can take the request."""
from __future__ import annotations

import json

import pytest

from services import run_registry
from services.blueprint.agent_contract import AgentResult
from services.blueprint.orchestrator import STOPPED_BY_PERSON, run
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(ats, tmp_path) -> BlueprintService:
    from services.smith.smith import bootstrap
    service = BlueprintService(output_dir=str(tmp_path))
    service.doc = ats
    service.root.mkdir(parents=True, exist_ok=True)
    service.save()
    bootstrap(service)
    return service


def ok(spec):
    return AgentResult(task_id=spec.task_id, agent=spec.agent)


def test_a_stop_asked_before_the_run_pauses_it_with_the_reason(svc, tmp_path):
    report = run(svc, ok, plan=["business_rules", "security"], should_stop=lambda: True)
    assert report.paused_because == STOPPED_BY_PERSON
    assert set(report.skipped) == {"business_rules", "security"} and not report.completed
    lines = [json.loads(l) for p in (tmp_path / ".forge" / "runs").glob("*.jsonl") for l in p.read_text().splitlines()]
    assert any(STOPPED_BY_PERSON in json.dumps(l) for l in lines)
    assert lines[-1]["event"] == "run:end"


def test_a_run_nobody_stops_is_not_paused(svc):
    report = run(svc, ok, plan=["business_rules"], should_stop=lambda: False)
    assert not report.paused_because and report.completed == ["business_rules"]


def test_the_stop_is_a_file_any_worker_reads_and_the_next_build_clears_it(tmp_path):
    assert not run_registry.stop_requested(tmp_path)
    run_registry.request_stop("p1", tmp_path)
    assert run_registry.stop_requested(tmp_path) and (tmp_path / ".forge" / "runs" / "STOP").is_file()
    run_registry.begin("p1", phase="build", output_dir=tmp_path)
    assert not run_registry.stop_requested(tmp_path)


def test_a_stopped_build_that_booted_is_handed_over(tmp_path, monkeypatch):
    """`_run_dag` after a paused-by-the-person run: what is built is handed
    over as it stands; no checks are started."""
    monkeypatch.setenv("FORGE_UI_DESIGNER", "forge")            # who designs the screens is settled
    from types import SimpleNamespace
    from routers import blueprint_generate as router

    out = tmp_path
    (out / "app").mkdir()
    (out / "app" / "package.json").write_text("{}")
    svc = BlueprintService.create(output_dir=str(out), app_id="x", name="Shop", domain="retail")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Home", "route": "/", "purpose": "home"}]
    svc.doc["runtime"] = {"build": {"status": "passed"},
                          "pages": {"planned": 1, "served": 1, "missing": [], "status": "complete"}}
    svc.save()
    report = SimpleNamespace(completed=[], failed=[], blocked=[], skipped=[], failed_because={},
                             skipped_because={}, blocked_because={}, paused_because=STOPPED_BY_PERSON, degraded={})
    monkeypatch.setattr("services.blueprint.orchestrator.run", lambda *a, **k: report)
    monkeypatch.setattr("services.smith.smith.settle_state_after_build", lambda svc, report: "IMPLEMENTATION")
    said = []
    result = router._run_dag(str(out), str(out / "app"), "", approved=True,
                             emit=lambda kind, data: said.append((kind, data)), phase="build")
    texts = [d.get("text", "") for k, d in said if k == "message"]
    assert any(t.startswith("Stopped, as you asked.") for t in texts), texts
    assert "checks" not in result
