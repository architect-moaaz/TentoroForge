"""Once the application is handed over, nothing the panel reads can say
"Building…": the registry reports the checks as their own phase, a new turn
keeps them, the hook branches on that phase without `status: "running"`, and
Stop reaches the engine."""
from __future__ import annotations

from pathlib import Path

from services import run_registry


def test_the_registry_reports_checks_as_their_own_phase_and_a_new_turn_keeps_them():
    run_registry.begin("p9", phase="build")
    run_registry.note("p9", "done", {"status": "complete"})
    assert run_registry.snapshot("p9")["status"] == "complete"
    run_registry.checking("p9")
    snap = run_registry.snapshot("p9")
    assert snap["active"] is False and snap["phase"] == "checking" and snap["checks"]["active"]
    run_registry.note("p9", "scorecard", {"summary": {"routes": {"total": 4, "green": 3, "red": 1, "untried": 0}},
                                          "phase": "fixing"})
    assert run_registry.snapshot("p9")["checks"]["phase"] == "fixing"
    assert run_registry.snapshot("p9")["checks"]["scorecard"]["routes"]["red"] == 1
    # A person's chat turn begins while the checks run: the checks are still there.
    run_registry.begin("p9", phase="define")
    assert run_registry.snapshot("p9")["checks"]["active"] and run_registry.snapshot("p9")["active"]
    run_registry.checks_done("p9", "done")
    assert run_registry.snapshot("p9")["checks"]["active"] is False


def test_a_persons_turn_in_flight_is_read_from_the_ledgers(tmp_path):
    from services.blueprint.run_ledger import TurnLedger
    assert not run_registry.turn_in_flight(tmp_path)
    ledger = TurnLedger(tmp_path, phase="change")
    assert run_registry.turn_in_flight(tmp_path)
    ledger.end()
    assert not run_registry.turn_in_flight(tmp_path)


def test_the_checks_ledger_is_its_own_phase_not_a_build(tmp_path):
    from services.blueprint.page_repair import _ledger
    with _ledger(str(tmp_path), 1, node="checks", phase="checking") as led:
        snap = run_registry.ledger_snapshot(tmp_path, turns=False)
        assert snap["active"] and snap["phase"] == "checking"
        led.heartbeat()
    snap = run_registry.ledger_snapshot(tmp_path, turns=False)
    assert not snap["active"] and snap["status"] == "complete"


def test_the_hook_treats_checking_as_not_building_and_stop_reaches_the_engine():
    root = Path(__file__).resolve().parents[3] / "frontend" / "src"
    hook = (root / "hooks" / "useBlueprintRun.ts").read_text()
    checking = hook[hook.index('snap.phase === "checking"'):]
    first_branch = checking[:checking.index("if (snap.active)")]
    assert 'status: "running"' not in first_branch
    assert "/build/stop" in hook[hook.index("const stop = useCallback"):hook.index("const start = useCallback")]
    panel = (root / "components" / "smith" / "SmithPanel.tsx").read_text()
    assert 'const busy = run.status === "running";' in panel
    assert "run.checks?.active" in panel and "checks-strip" in panel
    publish = (root / "components" / "deploy" / "PublishButton.tsx").read_text()
    assert '"ready" ? 30_000 : 5_000' in publish
