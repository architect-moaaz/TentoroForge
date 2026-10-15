"""After hand-over, every red is fixed by cause and the loop stops on yield:
after `DRY_STOP` turns in a row that turned nothing green, at `FIX_TURNS`,
or when the person stops it. Each green is said as one line.

Three separate loops used to run inside the build turn, each with its own
rounds and no cap on what a fix was worth (ECom L2: 56 minutes of process
repairs leaving 8 of 25 unfixed; 2026-10-11)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from services.blueprint import fix_to_green as ftg
from services.blueprint import scorecard as sc

DOC = {
    "version": 1,
    "roles": [{"id": "ROLE-001", "name": "Admin"}],
    "pages": [{"id": "PAGE-001", "name": "Catalogue", "route": "/"},
              {"id": "PAGE-002", "name": "Checkout", "route": "/checkout"},
              {"id": "PAGE-003", "name": "Orders", "route": "/orders"}],
    "workflows": [{"id": "FLOW-001", "name": "Place order", "trigger": {"kind": "manual"}, "steps": []}],
    "runtime": {"pages": {"planned": 3, "served": 3, "missing": [], "status": "complete"},
                "build": {"status": "passed"}},
}


class _Svc:
    def __init__(self, out: Path, doc: dict):
        self.out, self.doc = out, json.loads(json.dumps(doc))
        self.save()

    def save(self) -> None:
        p = self.out / ".forge" / "blueprint" / "current.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.doc))


def _wire(monkeypatch, svc, reds_by_turn):
    """The checks are faked: `reds_by_turn[n]` is what is still red after
    fix turn n (0 = the first check)."""
    state = {"turn": 0}
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: svc))
    monkeypatch.setattr("services.run_registry.turn_in_flight", lambda out: False)

    def check_everything(svc_, *a, **k):
        for criterion, items in reds_by_turn[0].items():
            sc.write(svc_, criterion, green=0, red=items, untried=[])
    monkeypatch.setattr(ftg, "_check_everything", check_everything)

    def check_again(svc_, output_dir, app_root, report, batch, **k):
        now = reds_by_turn[min(state["turn"], len(reds_by_turn) - 1)]
        for criterion in sc.CRITERIA:
            sc.write(svc_, criterion, green=0, red=now.get(criterion, []), untried=[])
    monkeypatch.setattr(ftg, "_check_again", check_again)
    turns = []

    def run_turn(pid, output_dir, ask, **k):
        turns.append((threading.current_thread().name, ask))
        time.sleep(0.05)                      # a repair takes a moment; three run on three threads
        return {"answer": "fixed", "edited_paths": ["src/x.tsx"]}
    orig_fix = ftg._fix

    def fix(batch, output_dir, **k):
        state["turn"] += 1
        orig_fix(batch, output_dir, **k)
    monkeypatch.setattr(ftg, "_fix", fix)
    return turns, run_turn


def test_reds_are_grouped_by_what_a_repair_is_addressed_to():
    reds = [{"criterion": "pages", "id": "PAGE-002", "label": "Checkout", "why": "500", "cause": "PAGE-002"},
            {"criterion": "routes", "id": "PAGE-002::Admin", "label": "Checkout as Admin", "why": "403", "cause": "PAGE-002"},
            {"criterion": "logic", "id": "FLOW-001", "label": "Place order", "why": "failed", "cause": "FLOW-001"},
            {"criterion": "logic", "id": "RULE-001", "label": "Stock cap", "why": "accepted", "cause": "RULE-001"},
            {"criterion": "access", "id": "ENTITY-001:Vendor", "label": "Product as Vendor", "why": "leaks", "cause": "ENTITY-001"}]
    groups = ftg.by_cause(reds)
    assert [(g["cause"], g["kind"], len(g["items"])) for g in groups] == [
        ("PAGE-002", "page", 2), ("FLOW-001", "process", 1), ("RULE-001", "rule", 1), ("ENTITY-001", "access", 1)]
    assert "as routes: 403" in ftg.ask_for(groups[0], DOC) and "/checkout" in ftg.ask_for(groups[0], DOC)
    assert "Place order (FLOW-001)" in ftg.ask_for(groups[1], DOC)


def test_pages_are_fixed_in_parallel_processes_alone_and_each_green_is_said(tmp_path, monkeypatch):
    svc = _Svc(tmp_path, DOC)
    sc.seed_from_boot(svc)
    page = lambda pid, name: sc.item(pid, name, "it answers HTTP 500", pid)  # noqa: E731
    flow = sc.item("FLOW-001", "Place order", "did not run through", "FLOW-001")
    first = {"pages": [page("PAGE-001", "Catalogue"), page("PAGE-002", "Checkout"), page("PAGE-003", "Orders")],
             "logic": [flow]}
    turns, run_turn = _wire(monkeypatch, svc, [first, {"logic": [flow]}, {}])
    said = []
    out = ftg.run_checks_to_green(svc, str(tmp_path), str(tmp_path / "app"), None,
                                  emit=lambda e, d: said.append((e, d)), run_turn=run_turn, record=False)
    assert out["turns"] == 2 and out["yield"] == [3, 1] and out["stopped"] is None
    page_asks = [t for t, ask in turns if "The build opened the page" in ask]
    assert len(page_asks) == 3 and len(set(page_asks)) == 3            # three threads at once
    flow_asks = [t for t, ask in turns if "Place order (FLOW-001)" in ask]
    assert flow_asks and "forge-fix" not in flow_asks[0]                # alone, on the caller's thread
    texts = [d["text"] for e, d in said if e == "message"]
    assert "Checkout: fixed — it answers HTTP 500 — no longer" in texts
    assert "Place order: fixed — did not run through — no longer" in texts
    assert texts[-1].startswith("Checks finished:")
    card = sc.read(svc.doc)
    assert card["status"] == "done" and card["fix"] == {"turns": 2, "yield": [3, 1], "stopped": None}
    assert card["criteria"]["smith"] == {"total": 4, "green": 4, "red": [], "untried": []}
    assert [e for e, d in said if e == "scorecard"]


def test_two_dry_turns_stop_the_loop_and_what_is_left_is_said(tmp_path, monkeypatch):
    svc = _Svc(tmp_path, DOC)
    sc.seed_from_boot(svc)
    stuck = {"pages": [sc.item("PAGE-002", "Checkout", "it answers HTTP 500", "PAGE-002")]}
    turns, run_turn = _wire(monkeypatch, svc, [stuck, stuck, stuck, stuck])
    said = []
    out = ftg.run_checks_to_green(svc, str(tmp_path), str(tmp_path / "app"), None,
                                  emit=lambda e, d: said.append((e, d)), run_turn=run_turn, record=False)
    # Three dry turns in a row end it (DRY_STOP): a list that yields nothing
    # is not worked for the whole time cap.
    assert out["turns"] == 3 and out["yield"] == [0, 0, 0] and out["stopped"] == "yield"
    assert len(turns) == 3
    closing = [d["text"] for e, d in said if e == "message"][-1]
    assert "Still not right (1): Checkout" in closing
    assert sc.read(svc.doc)["criteria"]["smith"]["red"][0]["id"] == "PAGE-002"


def test_the_cap_and_the_person_both_end_the_loop(tmp_path, monkeypatch):
    svc = _Svc(tmp_path, DOC)
    sc.seed_from_boot(svc)
    # Every turn turns one page green and leaves the rest: a yield of one each time.
    rounds = [{"pages": [sc.item(f"PAGE-{i:03d}", f"Q{i}", "500", f"PAGE-{i:03d}") for i in range(10, 20 - k)]}
              for k in range(0, 10)]
    turns, run_turn = _wire(monkeypatch, svc, rounds)
    monkeypatch.setattr(ftg, "FIX_TURNS", 6)      # the ceiling behind the time cap
    out = ftg.run_checks_to_green(svc, str(tmp_path), str(tmp_path / "app"), None,
                                  emit=None, run_turn=run_turn, record=False)
    assert out["turns"] == 6 and out["stopped"] == "turns"

    # THE CAP IS TIME. With the minutes used up after the first turn, the loop
    # ends on "time" with the list still open — and says so.
    svc3 = _Svc(tmp_path / "c", DOC)
    sc.seed_from_boot(svc3)
    rounds3 = [{"pages": [sc.item(f"PAGE-{i:03d}", f"Q{i}", "500", f"PAGE-{i:03d}") for i in range(10, 20 - k)]}
               for k in range(0, 10)]
    _turns3, run_turn3 = _wire(monkeypatch, svc3, rounds3)
    monkeypatch.setattr(ftg, "FIX_TURNS", 40)
    monkeypatch.setattr(ftg, "FIX_MINUTES", 0.0001)
    out3 = ftg.run_checks_to_green(svc3, str(tmp_path / "c"), str(tmp_path / "c" / "app"), None,
                                   emit=None, run_turn=run_turn3, record=False)
    assert out3["turns"] == 1 and out3["stopped"] == "time"

    svc2 = _Svc(tmp_path / "b", DOC)
    sc.seed_from_boot(svc2)
    turns, run_turn = _wire(monkeypatch, svc2, [{"pages": [sc.item("PAGE-002", "Checkout", "500", "PAGE-002")]}])
    said = []
    out = ftg.run_checks_to_green(svc2, str(tmp_path / "b"), str(tmp_path / "b" / "app"), None,
                                  emit=lambda e, d: said.append((e, d)), run_turn=run_turn, record=False,
                                  cancelled=lambda: True)
    assert out["turns"] == 0 and out["stopped"] == "stopped by the person" and turns == []
    assert sc.read(svc2.doc)["status"] == "stopped"
    assert [d["text"] for e, d in said if e == "message"][-1].startswith("Stopped checking.")


def test_a_smith_turn_that_saves_an_older_card_does_not_lose_the_checks_findings(tmp_path, monkeypatch):
    """The turn loads the engine's copy of the Blueprint, still carrying the
    hand-over card, and its save put it back over the checks' card
    (6132cfss, 2026-10-11): the loop restores its card after each turn."""
    svc = _Svc(tmp_path, DOC)
    sc.seed_from_boot(svc)
    stale = json.loads(json.dumps(svc.doc))                       # the hand-over card, as the engine's copy holds it
    stuck = {"pages": [sc.item("PAGE-002", "Checkout", "it answers HTTP 500", "PAGE-002")]}
    turns, run_turn = _wire(monkeypatch, svc, [stuck, {}])

    def clobbering_turn(pid, output_dir, ask, **k):
        (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(stale))
        return {"answer": "fixed", "edited_paths": ["x"]}
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: type("S", (), {"doc": json.loads(
                            (tmp_path / ".forge" / "blueprint" / "current.json").read_text())})()))
    seen = []
    orig = ftg._check_again

    def check_again(svc_, *a, **k):
        seen.append(sc.read(svc_.doc)["criteria"]["pages"]["red"][:])    # what the loop holds when it checks again
        return orig(svc_, *a, **k)
    monkeypatch.setattr(ftg, "_check_again", check_again)
    ftg.run_checks_to_green(svc, str(tmp_path), str(tmp_path / "app"), None, emit=None, run_turn=clobbering_turn, record=False)
    assert seen and seen[0] and seen[0][0]["id"] == "PAGE-002"       # the red survived the turn's stale save


def test_a_stop_is_written_as_the_ledgers_reason(tmp_path, monkeypatch):
    svc = _Svc(tmp_path, DOC)
    sc.seed_from_boot(svc)
    turns, run_turn = _wire(monkeypatch, svc, [{"pages": [sc.item("PAGE-002", "Checkout", "500", "PAGE-002")]}])
    ftg.run_checks_to_green(svc, str(tmp_path), str(tmp_path / "app"), None, emit=None, run_turn=run_turn,
                            record=True, cancelled=lambda: True)
    ledger = next((tmp_path / ".forge" / "runs").glob("*-checks.jsonl"))
    last = json.loads(ledger.read_text().splitlines()[-1])
    assert last["event"] == "run:end" and last["pausedBecause"] == "stopped by the person"
