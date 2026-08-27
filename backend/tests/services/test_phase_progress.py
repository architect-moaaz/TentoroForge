"""SSE must say which phase is running and how many are done.

A build emits a long stream of log lines with no sense of position. These
tests pin a `phase` event carrying ordinal, total and status, so a client
can render "5 of 12 · contracts" without parsing prose.
"""
import asyncio
import json

import pytest

from services.pipeline_graph import _NODES, with_phase_progress


def _cfg():
    q = asyncio.Queue()
    return {"configurable": {"emit_queue": q}}, q


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _phases(events):
    # sse_event() → {"event": <name>, "data": <json string>}
    return [json.loads(e["data"]) for e in events if e.get("event") == "phase"]


class TestWrapper:
    def test_emits_running_then_done_around_the_node(self):
        async def node(state, config):
            return {"ok": True}
        cfg, q = _cfg()
        wrapped = with_phase_progress(node, name="contracts", index=5, total=12)
        asyncio.run(wrapped({}, cfg))

        ph = _phases(_drain(q))
        assert [p["status"] for p in ph] == ["running", "done"]
        assert ph[0] == {
            "name": "contracts", "index": 5, "total": 12,
            "completed": 4, "status": "running",
        }
        assert ph[1]["completed"] == 5

    def test_passes_the_node_result_through_untouched(self):
        async def node(state, config):
            return {"plan": {"x": 1}, "quarantine": []}
        cfg, _ = _cfg()
        wrapped = with_phase_progress(node, name="schema", index=1, total=3)
        assert asyncio.run(wrapped({}, cfg)) == {"plan": {"x": 1}, "quarantine": []}

    def test_a_failing_phase_reports_failed_and_still_raises(self):
        # Swallowing the error would strand the build silently; the event is
        # for the user, not a substitute for the exception.
        async def node(state, config):
            raise RuntimeError("schema blew up")
        cfg, q = _cfg()
        wrapped = with_phase_progress(node, name="schema", index=2, total=12)
        with pytest.raises(RuntimeError, match="schema blew up"):
            asyncio.run(wrapped({}, cfg))

        ph = _phases(_drain(q))
        assert [p["status"] for p in ph] == ["running", "failed"]
        assert ph[-1]["completed"] == 1     # not counted as completed

    def test_works_without_an_emit_queue(self):
        # Smith and the test harness call nodes with no queue attached.
        async def node(state, config):
            return {"ok": True}
        wrapped = with_phase_progress(node, name="pages", index=1, total=1)
        assert asyncio.run(wrapped({}, {})) == {"ok": True}


class TestWiring:
    def test_every_real_phase_is_wrapped_and_numbered_in_order(self):
        real = [(n, f) for n, f in _NODES if not n.endswith("_gate")]
        assert len(real) >= 10, "spine should still have its phases"
        # Ordinals must be 1..N with no gaps — that is what "5 of 12" means.
        idx = [getattr(f, "_phase_index", None) for _, f in real]
        assert idx == list(range(1, len(real) + 1))
        assert all(getattr(f, "_phase_total", None) == len(real) for _, f in real)

    def test_gate_nodes_are_not_counted_as_phases(self):
        # Gates are sub-steps of the phase they follow; counting them would
        # double the total the user sees.
        gates = [(n, f) for n, f in _NODES if n.endswith("_gate")]
        assert gates, "spine should still have gate nodes"
        assert all(getattr(f, "_phase_index", None) is None for _, f in gates)
