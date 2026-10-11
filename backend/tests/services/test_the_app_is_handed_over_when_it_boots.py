"""The application is the person's the moment it boots: the build turn ends
with "Your application is built", the logins and the scorecard, and the
checks run afterwards in the background.

ECom L2 (2026-10-11): the app booted at 47 minutes and the person saw
"Building…" with Publish disabled for an hour and a half more while the
checks ran inside the build turn."""
from __future__ import annotations

from types import SimpleNamespace

from routers import blueprint_generate as router
from services.blueprint import scorecard as sc
from services.blueprint.service import BlueprintService


def _built(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="x", name="Shop", domain="retail")
    svc.doc["roles"] = [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Buyer"}]
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Catalogue", "route": "/", "purpose": "shop"},
                        {"id": "PAGE-002", "name": "Checkout", "route": "/checkout", "purpose": "pay"}]
    svc.doc["runtime"] = {"build": {"status": "passed_with_issues"},
                          "pages": {"planned": 2, "served": 1, "missing": ["/checkout"], "status": "short"}}
    svc.save()
    return svc


def _report():
    return SimpleNamespace(completed=["assemble"], failed=[], blocked=[], skipped=[], failed_because={},
                           skipped_because={}, blocked_because={}, paused_because="", degraded={})


def test_the_build_turn_hands_over_at_boot_and_leaves_the_checks_pending(tmp_path, monkeypatch):
    _built(tmp_path)
    monkeypatch.setattr("services.blueprint.orchestrator.run", lambda *a, **k: _report())
    monkeypatch.setattr("services.smith.smith.settle_state_after_build", lambda svc, report: "IMPLEMENTATION")
    checks_ran = []
    monkeypatch.setattr("services.blueprint.fix_to_green.run_checks_to_green",
                        lambda *a, **k: checks_ran.append(1))
    said = []
    result = router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True,
                             emit=lambda kind, data: said.append((kind, data)), phase="build")
    assert result["checks"] == {"output_dir": str(tmp_path), "app_root": str(tmp_path / "app"), "pending": True}
    assert checks_ran == []                                           # not in the turn
    texts = [d.get("text", "") for k, d in said if k == "message"]
    built = [t for t in texts if t.startswith("Your application is built")]
    assert built, texts
    assert "**Scorecard**" in built[0] and "| Pages built and working | 1 of 2 | 1 |" in built[0]
    assert "I'm now checking every page, route, process and rule" in built[0]
    assert not [d for k, d in said if k == "message" and d.get("status") == "asked"]   # no offer; it is doing it
    doc = BlueprintService.load(output_dir=str(tmp_path)).doc
    card = sc.read(doc)
    assert card["status"] == "checking" and card["criteria"]["pages"]["red"][0]["id"] == "PAGE-002"


def test_a_build_that_did_not_boot_hands_nothing_over(tmp_path, monkeypatch):
    svc = _built(tmp_path)
    svc.doc["runtime"] = {"build": {"status": "failed"}}
    svc.save()
    monkeypatch.setattr("services.blueprint.orchestrator.run", lambda *a, **k: _report())
    monkeypatch.setattr("services.smith.smith.settle_state_after_build", lambda svc, report: "IMPLEMENTATION")
    result = router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True,
                             emit=lambda kind, data: None, phase="build")
    assert "checks" not in result
    assert sc.read(BlueprintService.load(output_dir=str(tmp_path)).doc) is None


def test_the_checks_start_after_the_turn_and_speak_into_the_transcript(tmp_path, monkeypatch):
    import asyncio
    from services import run_registry
    remembered, noted = [], []
    monkeypatch.setattr(router, "_remember",
                        lambda loop, pid, role, text, meta=None, lock=None: remembered.append((role, text)))
    monkeypatch.setattr(run_registry, "note", lambda pid, event, data: noted.append((event, data)))

    def fake_checks(svc, output_dir, app_root, report, *, emit, cancelled):
        emit("message", {"text": "Checkout: fixed — opens now"})
        emit("scorecard", {"summary": {"pages": {"total": 2, "green": 2, "red": 0, "untried": 0}}, "phase": "done"})
        return {"turns": 1, "yield": [1], "stopped": None, "card": {}}
    monkeypatch.setattr("services.blueprint.fix_to_green.run_checks_to_green", fake_checks)
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: object()))

    async def go():
        loop = asyncio.get_running_loop()
        fut = router._start_checks(loop, "p-checks", str(tmp_path), str(tmp_path / "app"))
        assert run_registry.snapshot("p-checks")["checks"]["active"]
        assert run_registry.snapshot("p-checks")["phase"] == "checking"
        await fut
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert remembered == [("assistant", "Checkout: fixed — opens now")]
    assert ("scorecard", {"summary": {"pages": {"total": 2, "green": 2, "red": 0, "untried": 0}},
                          "phase": "done"}) in noted
    snap = run_registry.snapshot("p-checks")
    assert snap["checks"]["active"] is False and snap["checks"]["phase"] == "done"
