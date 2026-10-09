"""An approved build is the engineer's: feature by feature, proven as it
goes, with nothing repaired after.

The build entry ran the graph once over everything, handed the app over,
and then ran huddles, a page repair and the statements over whatever that
left (forge-v3, 2026-10-09: 24 minutes of repair on TStyle's one page,
statements untried). Now the engineer builds each feature and tries its
statements before the next; the entry announces what was proven.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.blueprint.service import BlueprintService


@pytest.fixture()
def project(tmp_path, monkeypatch):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    svc.doc["state"] = "PLAN_REVIEW"
    svc.doc["modules"] = [{"id": "MODULE-001", "name": "Catalogue", "pages": ["PAGE-001"]}]
    svc.doc["pages"] = [{"id": "PAGE-001", "route": "/", "pattern": "dashboard", "module": "MODULE-001",
                         "purpose": "home", "name": "Home"}]
    svc.doc["runtime"] = {"build": {"status": "passed", "install": 0, "build": 0}}
    svc.save()
    (tmp_path / "app").mkdir()
    monkeypatch.setattr("services.blueprint.executors.RunUsage.for_app",
                        classmethod(lambda cls, s, **k: type("U", (), {"summary": lambda self: {}})()))
    monkeypatch.setattr("services.blueprint.executors.tiered_router", lambda **k: object())
    monkeypatch.setattr("services.blueprint.executors.make_executor", lambda *a, **k: object())
    monkeypatch.setattr("services.blueprint.observer.anthropic_observer", lambda *a, **k: None)
    return svc


def test_an_approved_build_goes_to_the_engineer_and_nothing_is_repaired_after(project, tmp_path, monkeypatch):
    from routers import blueprint_generate as router
    calls: dict = {}

    def engineer(output_dir, app_root, **kw):
        from services.blueprint.orchestrator import RunReport
        calls.update(kw, output_dir=output_dir)
        return {"features": [{"feature": "MODULE-001"}], "statements": {"passed": 3}, "stopped": "",
                "state": "VERIFICATION", "report": RunReport(completed=["assemble"])}
    monkeypatch.setattr("services.engineer.build.build", engineer)
    monkeypatch.setattr(router, "_finish_unfinished_pages",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("repaired after the engineer")))
    monkeypatch.setattr("services.blueprint.orchestrator.run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("the graph was run whole")))
    said: list[tuple[str, dict]] = []
    out = router._run_dag(str(tmp_path), str(tmp_path / "app"), "build it", approved=True,
                          emit=lambda kind, data: said.append((kind, data)), app_name="Shop")
    assert calls["output_dir"] == str(tmp_path) and calls["description"] == "build it"
    assert calls["app_name"] == "Shop" and "done_nodes" in calls and calls["observer"] is not None
    assert calls["svc"] is not None and calls["svc"].doc.get("application"), "the entry's own document is the engineer's"
    assert out["phase"] == "build" and out["state"]
    texts = [d.get("text", "") for k, d in said if k == "message"]
    assert any("Your application is built" in t for t in texts), "handed over"


def test_a_definition_run_still_goes_through_the_graph(project, tmp_path, monkeypatch):
    from routers import blueprint_generate as router
    ran = {}

    def run(svc, executor, *, plan, **k):
        ran["plan"] = list(plan)
        return SimpleNamespace(completed=list(plan), failed=[], blocked=[], paused_because="", skipped=[])
    monkeypatch.setattr("services.blueprint.orchestrator.run", run)
    monkeypatch.setattr("services.engineer.build.build",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("the engineer builds, it does not define")))
    router._run_dag(str(tmp_path), str(tmp_path / "app"), "define it", approved=False,
                    emit=lambda kind, data: None, phase="define")
    assert ran["plan"] and set(ran["plan"]) <= {"requirements", "figma_intelligence"}


def test_a_resumed_build_counts_what_was_complete_before_it(project, tmp_path, monkeypatch):
    """Crumb's resume completed only its last nodes, and the state walk left a
    built, proven app at IMPLEMENTATION (2026-10-09)."""
    from routers import blueprint_generate as router
    from services.blueprint.orchestrator import RunReport
    monkeypatch.setattr("services.engineer.build.build",
                        lambda od, app, **kw: {"features": [], "statements": {}, "stopped": "", "state": "",
                                               "report": RunReport(completed=["verification"])})
    monkeypatch.setattr("services.blueprint.orchestrator.completed_nodes",
                        lambda doc, confirmed=None: {"install", "assemble", "page_code"})
    monkeypatch.setattr(router, "_finish_unfinished_pages", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr("services.smith.smith.settle_state_after_build",
                        lambda svc, report: seen.update(completed=sorted(report.completed)) or "PREVIEW")
    router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True, emit=lambda k, d: None)
    assert seen["completed"] == ["assemble", "install", "page_code", "verification"]
