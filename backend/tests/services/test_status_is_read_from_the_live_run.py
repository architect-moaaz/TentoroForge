"""A status answer starts from what is running right now, as the ledgers on
disk say it — never from the last check. Asked "what is the % completion
now", Smith described fixes in progress while the turn it meant had been
dead for forty minutes (pcn4owv7, 2026-10-15)."""
from __future__ import annotations

import json
import time

from services import run_registry
from routers.blueprint_generate import _lifecycle_verb


def _ledger(tmp_path, stem: str, events: list[dict]):
    runs = tmp_path / ".forge" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{stem}.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def test_a_running_turn_is_said_as_running(tmp_path):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _ledger(tmp_path, "20261015-101619-smith-turn", [
        {"event": "run:start", "phase": "define", "at": now, "pid": 9, "elapsedMs": 0},
        {"event": "run:heartbeat", "at": now, "elapsedMs": 20000},
    ])
    line = run_registry.live_state(tmp_path)
    assert line.startswith("RIGHT NOW: a turn is running") and "last sign of life" in line


def test_a_killed_turn_is_said_as_stopped_and_nothing_running(tmp_path):
    _ledger(tmp_path, "20261015-024202-smith-turn", [
        {"event": "run:start", "phase": "define", "at": "2026-10-15T02:42:02Z", "pid": 9, "elapsedMs": 0},
        {"event": "run:crashed", "error": "the platform restarted while it ran", "at": "2026-10-15T03:14:54Z"},
    ])
    line = run_registry.live_state(tmp_path)
    assert line.startswith("NOTHING IS RUNNING NOW") and "stopped by a platform restart at 03:14 UTC" in line


def test_a_finished_build_is_said_as_ended(tmp_path):
    _ledger(tmp_path, "20261014-123930-370f91", [
        {"event": "run:start", "phase": "build", "at": "2026-10-14T12:39:30Z", "pid": 9, "elapsedMs": 0},
        {"event": "run:end", "at": "2026-10-14T13:16:33Z", "completed": ["pages"], "failed": []},
    ])
    assert run_registry.live_state(tmp_path) == "NOTHING IS RUNNING NOW. The last build ended at 13:16 UTC."
    assert run_registry.live_state(tmp_path / "nowhere") == "NOTHING HAS RUN on this application yet."


def test_a_status_question_in_a_sentence_is_the_status_verb():
    for ask in ("what is the current status and how long does it take to complete the build process",
                "What is the progress in terms of % completion", "Its more than an hour with no status update, what is the % completion now",
                "is it still working?", "any update?", "where are we"):
        assert _lifecycle_verb(ask) == "status", ask
    # A change that mentions status is a change.
    assert _lifecycle_verb("fix the status badge on the dashboard") is None
    assert _lifecycle_verb("add a progress bar to the import page") is None
    assert _lifecycle_verb("status") == "status" and _lifecycle_verb("build") == "build"
