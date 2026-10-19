"""Eight asks in two weeks were "continue", "resume", "rerun" or "Build app"
typed after a build whose process went away or whose step failed; they got
the card to press, a canned line, an invented change, or nothing (forge-v3,
2026-10-03..17). The ledger said where it stopped the whole time."""
from __future__ import annotations

import json
import time

from services import run_registry


def _ledger(tmp_path, name: str, events: list[dict]) -> None:
    runs = tmp_path / ".forge" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{name}.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _at(offset: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - offset))


def test_a_build_whose_process_went_away_is_dead(tmp_path):
    _ledger(tmp_path, "20261016-093000-abc123", [
        {"event": "run:start", "phase": "build", "at": _at(3600)},
        {"event": "plan", "nodes": ["requirements", "page_contracts", "pages"]},
        {"event": "node:start", "node": "page_contracts", "at": _at(3500)},
        {"event": "run:crashed", "error": "the platform restarted while it ran", "at": _at(3400)},
    ])
    dead = run_registry.dead_build(tmp_path)
    assert dead and dead["stage"] == "page_contracts" and dead["phase"] == "build"
    line = run_registry.stopped_line(dead)
    assert "stopped at" in line and "page_contracts" in line and "the platform restarted" in line


def test_a_build_that_ended_with_a_failed_step_is_dead_and_names_it(tmp_path):
    _ledger(tmp_path, "20261016-093000-abc123", [
        {"event": "run:start", "phase": "model", "at": _at(900)},
        {"event": "run:end", "at": _at(800), "completed": ["requirements"], "failed": ["page_contracts"],
         "blocked": [], "skipped": [], "pausedBecause": ""},
    ])
    dead = run_registry.dead_build(tmp_path)
    assert dead and dead["failedNodes"] == ["page_contracts"] and dead["phase"] == "model"
    assert "page_contracts did not finish" in run_registry.stopped_line(dead)


def test_a_finished_build_or_a_running_one_is_not_dead(tmp_path):
    _ledger(tmp_path, "20261016-093000-abc123", [
        {"event": "run:start", "phase": "build", "at": _at(900)},
        {"event": "run:end", "at": _at(800), "completed": ["pages"], "failed": [], "blocked": [], "skipped": []},
    ])
    assert run_registry.dead_build(tmp_path) is None
    _ledger(tmp_path, "20261016-094000-def456", [
        {"event": "run:start", "phase": "build", "at": _at(60)},
        {"event": "run:heartbeat", "at": _at(5)},
    ])
    assert run_registry.dead_build(tmp_path) is None


def test_a_turn_or_check_ledger_is_not_a_build(tmp_path):
    _ledger(tmp_path, "20261016-093000-smith-turn", [
        {"event": "run:start", "phase": "build", "at": _at(900)},
        {"event": "run:crashed", "error": "gone", "at": _at(800)},
    ])
    assert run_registry.last_build(tmp_path) is None and run_registry.dead_build(tmp_path) is None


def test_the_words_that_mean_go_on():
    from routers.blueprint_generate import _asks_to_carry_on
    for word in ("continue", "Resume", "rerun", "Build app", "build it again", "carry on", "try again.",
                 "restart and rebuild", "Rebuild"):
        assert _asks_to_carry_on(word), word
    for word in ("continue with the orders page", "fix the status badge", "build a calculator", ""):
        assert not _asks_to_carry_on(word), word


def test_the_rebuild_verb_hands_a_dead_build_back_to_be_run(tmp_path):
    from services.smith4 import verbs
    _ledger(tmp_path, "20261016-093000-abc123", [
        {"event": "run:start", "phase": "build", "at": _at(900)},
        {"event": "node:start", "node": "pages", "at": _at(850)},
        {"event": "run:crashed", "error": "its process went away", "at": _at(800)},
    ])
    ctx = verbs.Ctx(output_dir=str(tmp_path), project_id="p", message="rebuild", ask="rebuild")
    out = verbs.rebuild(ctx, {"verb": "rebuild"})
    assert out.status == "handoff" and out.follow_up == "run:build"
    assert "stopped at" in out.said and "Starting it again" in out.said
