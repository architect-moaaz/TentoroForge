"""A Smith turn is on disk, so a panel whose stream dropped finds it again.

A turn was only in the run registry — the memory of the one worker running
it. The panel's poll landed on the other worker, found nothing, and said the
turn "could not be picked back up"; a turn whose worker died left the
person's message unanswered for good (ihf6pjga, 2026-10-05).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import time
from types import SimpleNamespace

from services import run_registry
from services.blueprint.run_ledger import RunLedger, TurnLedger


def _age(path, seconds):
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_a_turn_at_work_is_running_to_any_worker(tmp_path):
    turn = TurnLedger(tmp_path, phase="define")

    snap = run_registry.ledger_snapshot(tmp_path)
    assert snap["active"] and snap["status"] == "running"

    turn.end()
    snap = run_registry.ledger_snapshot(tmp_path)
    assert snap["status"] == "complete" and not snap["active"]


def test_a_turn_that_raised_says_so(tmp_path):
    TurnLedger(tmp_path).end(ValueError("bad"))
    assert run_registry.ledger_snapshot(tmp_path)["status"] == "error"


def test_a_turn_is_not_a_build_in_flight(tmp_path):
    router = importlib.import_module("routers.blueprint_generate")
    TurnLedger(tmp_path)
    assert router.build_in_flight(tmp_path) is None, "the turn asking would refuse its own build"


def test_a_turn_still_talking_after_its_build_ended_is_running(tmp_path):
    turn = TurnLedger(tmp_path, phase="build")
    time.sleep(1.1)  # the build's ledger is named a second later
    build = RunLedger(tmp_path, time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-abc123")
    build.planned(["a", "b"])
    build.node_done("a")
    build.node_done("b")
    build.finish(SimpleNamespace(completed=["a", "b"]))

    snap = run_registry.ledger_snapshot(tmp_path)
    assert snap["active"], "the turn goes on to say what was built"
    assert (snap["nodesDone"], snap["nodesTotal"]) == (2, 2), "with the build's steps"

    turn.end()
    assert not run_registry.ledger_snapshot(tmp_path)["active"]


def test_a_turn_whose_process_died_is_said_once(tmp_path, monkeypatch):
    turn = TurnLedger(tmp_path)
    turn._stop.set()  # the pulse dies with the process
    _age(turn.ledger.path, run_registry.LEDGER_STALE_S + 30)

    snap = run_registry.ledger_snapshot(tmp_path)
    assert snap["interrupted"] and snap["status"] == "error"
    assert "Send it again" in snap["error"]

    router = importlib.import_module("routers.blueprint_generate")
    said: list[str] = []
    monkeypatch.setattr(router, "_remember", lambda _loop, _pid, role, text, *a, **k: said.append(text))
    project = SimpleNamespace(id="p1", output_dir=str(tmp_path))

    async def poll_twice():
        for _ in range(2):
            snap = run_registry.ledger_snapshot(tmp_path)
            if snap.get("interrupted"):
                router._interrupted_turn(project, snap)
    asyncio.run(poll_twice())

    assert len(said) == 1 and "Send it again" in said[0]
    last = json.loads(turn.ledger.path.read_text().splitlines()[-1])
    assert last["event"] == "run:crashed"
