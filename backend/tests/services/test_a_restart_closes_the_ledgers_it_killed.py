"""Ecom L1 (2026-10-11): the backend was restarted under a running engineer
build; its ledger stayed open, the panel read it as "Building…" for three
minutes, and no Build press was taken."""
import json

from services import run_registry


def _ledger(root, app, name, *events):
    runs = root / app / ".forge" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{name}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), "utf-8")
    return runs / f"{name}.jsonl"


def test_an_open_ledger_is_closed_at_startup_and_an_ended_one_is_left_alone(tmp_path):
    open_one = _ledger(tmp_path, "a1", "20261011-010850-engineer",
                       {"event": "run:start", "at": "2026-10-10T19:38:50Z"},
                       {"event": "run:heartbeat", "at": "2026-10-10T19:55:10Z"})
    ended = _ledger(tmp_path, "a1", "20261010-193850-82157c",
                    {"event": "run:start"}, {"event": "run:end", "at": "2026-10-10T19:34:10Z"})
    turn = _ledger(tmp_path, "b2", "20261010-185045-4c92ad-smith-turn", {"event": "run:start"})
    assert sorted(run_registry.close_orphaned_ledgers(tmp_path)) == [
        "20261010-185045-4c92ad-smith-turn", "20261011-010850-engineer"]
    assert json.loads(open_one.read_text().splitlines()[-1])["event"] == "run:crashed"
    assert json.loads(turn.read_text().splitlines()[-1])["event"] == "run:crashed"
    assert ended.read_text().count("\n") == 2
    assert run_registry.close_orphaned_ledgers(tmp_path) == [], "closed once"
    assert run_registry.ledger_snapshot(tmp_path / "a1")["active"] is False
