"""A long turn is not silent between the ten-minute note and the end: the
loop writes each step to its ledger, the status line reads it, and the
released turn posts it every few minutes — or that the ledger went quiet."""
from __future__ import annotations

import asyncio
import json

from routers.blueprint_generate import _post_progress, progress_line
from services import run_registry
from services.blueprint.run_ledger import TurnLedger
from services.smith4.turn import step_line


def test_the_loop_writes_its_step_and_the_status_line_reads_it(tmp_path):
    ledger = TurnLedger(tmp_path, phase="define")
    try:
        assert str(tmp_path.resolve()) in run_registry.TURNS
        run_registry.turn_step(tmp_path, step_line(6, "open_page", {"route": "/calendar", "as": "Consumer"}))
        run_registry.turn_step(tmp_path / "elsewhere", "ignored: no turn here")
        lines = [json.loads(l) for l in (tmp_path / ".forge" / "runs").glob("*.jsonl").__next__().read_text().splitlines()]
        steps = [l for l in lines if l["event"] == "turn:step"]
        assert steps == [{**steps[0], "text": "step 6: open_page /calendar as Consumer"}]
        snap = run_registry.ledger_snapshot(tmp_path)
        assert snap["active"] and snap["step"] == "step 6: open_page /calendar as Consumer"
        assert "Last step: step 6: open_page /calendar as Consumer" in run_registry.live_state(tmp_path)
        assert progress_line(snap) == "Still at it (0 min): step 6: open_page /calendar as Consumer."
    finally:
        ledger.end()
    assert str(tmp_path.resolve()) not in run_registry.TURNS
    assert progress_line(run_registry.ledger_snapshot(tmp_path)) is None


def test_a_released_turn_posts_its_step_then_that_it_stopped(tmp_path):
    posted = []
    emit = lambda e, d: posted.append(d["text"]) if e == "message" else None
    ledger = TurnLedger(tmp_path, phase="define")
    run_registry.turn_step(tmp_path, "step 3: write_page_code /transactions")

    async def scenario():
        loop = asyncio.get_running_loop()
        inner = loop.create_future()
        task = asyncio.ensure_future(_post_progress(inner, tmp_path, emit, every=0.05))
        await asyncio.sleep(0.12)                 # at least one progress line
        ledger.end(RuntimeError("the worker went away"))   # the ledger stops: crashed
        await asyncio.wait_for(task, 2)
        inner.set_result({"status": "resolved"})
    asyncio.run(scenario())
    assert posted and posted[0].startswith("Still at it (0 min): step 3: write_page_code /transactions")
    assert "That turn stopped at" in posted[-1] and "Say “carry on”" in posted[-1]
