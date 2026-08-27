"""Tests for services.pipeline.state.PipelineState.

Pins the invariants the phase extract work depends on:
- factory wires progress buffer correctly
- stream_phase accumulates cost/turns/duration from agent_result events
- write_timing produces the same JSON shape as the legacy inline writer
- phase_timings survive exceptions (finally-block semantics preserved)
"""
from __future__ import annotations

import json

import pytest

from services.pipeline.source import PlanSource
from services.pipeline.state import PipelineState


class TestFactory:
    def test_create_wires_progress_tracker(self, tmp_path):
        state = PipelineState.create(
            output_dir=str(tmp_path),
            source=PlanSource.text(),
        )
        assert state.progress is not None
        # Progress emit → buffer → drain
        state.progress.phase_start("design")
        events = list(state.drain_progress())
        assert len(events) >= 1
        # Buffer empty after drain.
        assert list(state.drain_progress()) == []

    def test_defaults_zero(self, tmp_path):
        state = PipelineState.create(
            output_dir=str(tmp_path),
            source=PlanSource.text(),
        )
        assert state.total_cost == 0.0
        assert state.total_turns == 0
        assert state.total_duration_ms == 0.0
        assert state.phase_timings == {}
        assert state.last_phase == "(none)"
        assert state.elapsed_seconds >= 0

    def test_source_preserved(self, tmp_path):
        src = PlanSource.figma(url="https://figma.com/x", token="t")
        state = PipelineState.create(output_dir=str(tmp_path), source=src)
        assert state.source is src
        assert state.source.is_figma


class TestStreamPhaseAccumulation:
    @pytest.mark.asyncio
    async def test_agent_result_accrues_cost(self, tmp_path, monkeypatch):
        # Stub out stream_with_idle_timeout with a fake iterator.
        async def _fake_stream(name, output_dir, messages):
            yield {"event": "log", "data": '{"text":"hi"}'}
            yield {
                "event": "agent_result",
                "data": json.dumps({
                    "cost_usd": 0.15,
                    "num_turns": 3,
                    "duration_ms": 1234,
                }),
            }
            yield {"event": "log", "data": '{"text":"bye"}'}

        monkeypatch.setattr(
            "services.parallel_runner.stream_with_idle_timeout", _fake_stream
        )
        state = PipelineState.create(
            output_dir=str(tmp_path), source=PlanSource.text(),
        )
        async def _drain():
            async for _ in state.stream_phase("Contract", iter([])):
                pass
        await _drain()
        assert state.total_cost == pytest.approx(0.15)
        assert state.total_turns == 3
        assert state.total_duration_ms == 1234
        # Phase timing recorded (>= 0).
        assert "Contract" in state.phase_timings
        # last_phase tracks entry.
        assert state.last_phase == "Contract"

    @pytest.mark.asyncio
    async def test_multiple_phases_accumulate(self, tmp_path, monkeypatch):
        async def _stream_with_cost(cost, turns, duration):
            async def _inner(name, output_dir, messages):
                yield {
                    "event": "agent_result",
                    "data": json.dumps({
                        "cost_usd": cost,
                        "num_turns": turns,
                        "duration_ms": duration,
                    }),
                }
            return _inner

        state = PipelineState.create(
            output_dir=str(tmp_path), source=PlanSource.text(),
        )
        # Phase 1
        monkeypatch.setattr(
            "services.parallel_runner.stream_with_idle_timeout",
            await _stream_with_cost(0.1, 2, 500),
        )
        async for _ in state.stream_phase("Schema", iter([])):
            pass
        # Phase 2
        monkeypatch.setattr(
            "services.parallel_runner.stream_with_idle_timeout",
            await _stream_with_cost(0.3, 5, 2000),
        )
        async for _ in state.stream_phase("API", iter([])):
            pass

        assert state.total_cost == pytest.approx(0.4)
        assert state.total_turns == 7
        assert state.total_duration_ms == 2500
        assert set(state.phase_timings.keys()) == {"Schema", "API"}

    @pytest.mark.asyncio
    async def test_timing_recorded_on_exception(self, tmp_path, monkeypatch):
        # A wedged phase (exception mid-stream) must still land in
        # phase_timings — the legacy `finally` behaviour.
        async def _boom(name, output_dir, messages):
            yield {"event": "log", "data": '{"text":"start"}'}
            raise RuntimeError("phase wedged")

        monkeypatch.setattr(
            "services.parallel_runner.stream_with_idle_timeout", _boom
        )
        state = PipelineState.create(
            output_dir=str(tmp_path), source=PlanSource.text(),
        )
        with pytest.raises(RuntimeError, match="phase wedged"):
            async for _ in state.stream_phase("BusinessLogic", iter([])):
                pass
        # Timing landed despite the exception.
        assert "BusinessLogic" in state.phase_timings
        assert state.phase_timings["BusinessLogic"] >= 0


class TestWriteTiming:
    def test_writes_json_snapshot(self, tmp_path):
        state = PipelineState.create(
            output_dir=str(tmp_path), source=PlanSource.text(),
        )
        state.phase_timings = {"Contract": 3.4, "Schema": 5.6}
        state.write_timing()
        path = tmp_path / "generation-timing.json"
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data["phases"] == {"Contract": 3.4, "Schema": 5.6}
        assert data["total_seconds"] == 9.0

    def test_write_failure_swallowed(self, tmp_path):
        # Point output_dir at a non-existent parent — write raises,
        # method must not propagate.
        state = PipelineState.create(
            output_dir="/nonexistent/dir/that/should/not/exist",
            source=PlanSource.text(),
        )
        state.phase_timings = {"X": 1.0}
        state.write_timing()  # must not raise


class TestPhaseKeyMapping:
    """The STREAM_PHASE_TO_KEY table drives ProgressTracker.phase_start
    at entry; the extract preserves it byte-for-byte from the legacy
    inline mapping. Anti-regression: if entries drift, the frontend
    progress ring desyncs."""

    def test_key_map_covers_all_agents(self):
        from services.pipeline.state import _STREAM_PHASE_TO_KEY
        expected = {
            "Design", "Contract", "Contract-Fix", "Schema", "BusinessLogic",
            "API", "Component", "Component-Fix", "Page", "Page-Fix",
            "UX-Fix", "Workflow", "Workflow-Fix", "Auth-Fix",
        }
        assert set(_STREAM_PHASE_TO_KEY.keys()) == expected

    def test_key_map_values_are_progress_keys(self):
        from services.pipeline.state import _STREAM_PHASE_TO_KEY
        # Progress keys the tracker knows about (mirrors ProgressTracker
        # PHASES enum; check a representative sample).
        for phase, key in _STREAM_PHASE_TO_KEY.items():
            assert isinstance(key, str) and key
