"""Task 3b — orchestrate_planner routes through decomposition when
`should_decompose` says yes AND we have an output_dir. Falls back to
one-shot on any failure so a broken decomposition never blocks planning."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from services.smith_agent_adapters import orchestrate_planner


def _plan_shape() -> dict:
    """Minimal plan shape that survives plan_dict_to_artifact +
    apply_plan_wires without exploding."""
    return {
        "actors":      [],
        "data_models": [{"name": "Thing", "fields": [{"name": "id"}]}],
        "entities":    [{"name": "Thing", "fields": [{"name": "id"}]}],
        "workflows":   [],
        "pages":       [{"route": "/things", "archetype": "list", "entity": "Thing", "name": "Things"}],
    }


async def _fake_units(skel: dict, out: str, **_) -> dict:
    return {**skel, "pages": skel.get("pages") or []}


def test_decomposition_used_when_gate_fires(monkeypatch):
    """Large prompt + output_dir → skeleton call + parallel per-unit
    call. The one-shot planner MUST NOT be invoked."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Silence the actor-critic loop so we're testing the branching, not
    # the critic behavior.
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "0")

    with patch(
        "services.app_decomposition.should_decompose", return_value=True,
    ), patch(
        "agents.app_map_agent.run_app_map_planner", return_value=_plan_shape(),
    ) as m_skel, patch(
        "services.per_unit_authoring.author_all_units_async",
        side_effect=_fake_units,
    ) as m_units, patch(
        "agents.planner.run_planner_oneshot", return_value=_plan_shape(),
    ) as m_oneshot:
        art = asyncio.run(orchestrate_planner(
            description="a big rich domain prompt",
            output_dir="/tmp/test-decomp-abc",
        ))
        assert m_skel.called,  "skeleton planner must run when gate fires"
        assert m_units.called, "parallel per-unit authoring must run"
        assert not m_oneshot.called, "one-shot must NOT run when decomposition succeeds"
        assert art is not None


def test_oneshot_used_when_gate_declines(monkeypatch):
    """Small-prompt path stays on the fast one-shot planner."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Silence the actor-critic loop so we're testing the branching, not
    # the critic behavior.
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "0")

    with patch(
        "services.app_decomposition.should_decompose", return_value=False,
    ), patch(
        "agents.planner.run_planner_oneshot", new_callable=AsyncMock,
        return_value=_plan_shape(),
    ) as m_oneshot, patch(
        "agents.app_map_agent.run_app_map_planner",
    ) as m_skel:
        art = asyncio.run(orchestrate_planner(
            description="tiny prompt",
            output_dir="/tmp/test-oneshot-abc",
        ))
        assert m_oneshot.called
        assert not m_skel.called
        assert art is not None


def test_oneshot_used_when_no_output_dir(monkeypatch):
    """Decomposition needs output_dir to write per-page registry slices;
    without one, degrade to the one-shot path."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Silence the actor-critic loop so we're testing the branching, not
    # the critic behavior.
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "0")

    with patch(
        "services.app_decomposition.should_decompose", return_value=True,
    ), patch(
        "agents.planner.run_planner_oneshot", new_callable=AsyncMock,
        return_value=_plan_shape(),
    ) as m_oneshot, patch(
        "agents.app_map_agent.run_app_map_planner",
    ) as m_skel:
        art = asyncio.run(orchestrate_planner(
            description="big prompt", output_dir=None,
        ))
        assert m_oneshot.called
        assert not m_skel.called, "no output_dir → don't decompose"
        assert art is not None


def test_skeleton_failure_falls_back_to_oneshot(monkeypatch):
    """Broken decomposition must NEVER block generation."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Silence the actor-critic loop so we're testing the branching, not
    # the critic behavior.
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "0")

    def _boom(*_a, **_kw):
        raise RuntimeError("skeleton broke")

    with patch(
        "services.app_decomposition.should_decompose", return_value=True,
    ), patch(
        "agents.app_map_agent.run_app_map_planner", side_effect=_boom,
    ), patch(
        "agents.planner.run_planner_oneshot", new_callable=AsyncMock,
        return_value=_plan_shape(),
    ) as m_oneshot:
        art = asyncio.run(orchestrate_planner(
            description="big", output_dir="/tmp/test-skel-fail",
        ))
        assert m_oneshot.called, "skeleton crash → fall back to one-shot"
        assert art is not None


def test_per_unit_failure_falls_back_to_oneshot(monkeypatch):
    """A parallel-authoring crash after a successful skeleton also
    degrades to one-shot rather than shipping a half-authored plan."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Silence the actor-critic loop so we're testing the branching, not
    # the critic behavior.
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "0")

    async def _boom_units(*_a, **_kw):
        raise RuntimeError("units crashed")

    with patch(
        "services.app_decomposition.should_decompose", return_value=True,
    ), patch(
        "agents.app_map_agent.run_app_map_planner", return_value=_plan_shape(),
    ), patch(
        "services.per_unit_authoring.author_all_units_async",
        side_effect=_boom_units,
    ), patch(
        "agents.planner.run_planner_oneshot", new_callable=AsyncMock,
        return_value=_plan_shape(),
    ) as m_oneshot:
        art = asyncio.run(orchestrate_planner(
            description="big", output_dir="/tmp/test-units-fail",
        ))
        assert m_oneshot.called
        assert art is not None


def test_decomposition_survives_nested_event_loop(monkeypatch):
    """The bug we hit live: ``run_app_map_planner`` uses ``asyncio.run()``
    internally to await its LLM coroutine. When ``orchestrate_planner``
    (async) calls it directly, that ``asyncio.run()`` explodes with
    "cannot be called from a running event loop." The fix wraps the sync
    call in ``asyncio.to_thread`` so it runs in a fresh worker thread
    with no active loop.

    This test mimics the failure mode by making the injected _query
    return an awaitable (which is what triggers ``asyncio.run()`` in
    the real ``run_app_map_planner``)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "0")

    called_from_thread: list[bool] = []

    def _skeleton_sync(_prompt: str, _dom=None) -> dict:
        # The signature run_app_map_planner uses. Mimic what the real
        # sync function would do: call an async _query, then await it
        # with asyncio.run(). If we're running from inside an event
        # loop, this raises "asyncio.run() cannot be called…". If our
        # asyncio.to_thread wrapper is in place, we're in a thread
        # with no loop, so asyncio.run() works.
        import asyncio as _a
        import threading
        called_from_thread.append(threading.current_thread() is not threading.main_thread())

        async def _fake_query():
            return _plan_shape()
        return _a.run(_fake_query())

    with patch(
        "services.app_decomposition.should_decompose", return_value=True,
    ), patch(
        "agents.app_map_agent.run_app_map_planner", side_effect=_skeleton_sync,
    ), patch(
        "services.per_unit_authoring.author_all_units_async",
        side_effect=_fake_units,
    ), patch(
        "agents.planner.run_planner_oneshot", new_callable=AsyncMock,
        return_value=_plan_shape(),
    ) as m_oneshot:
        art = asyncio.run(orchestrate_planner(
            description="a big prompt",
            output_dir="/tmp/test-nested-loop",
        ))

    assert called_from_thread and called_from_thread[0] is True, (
        "run_app_map_planner must be called from a worker thread so its "
        "internal asyncio.run() has no active event loop to fight"
    )
    assert not m_oneshot.called, "successful decomposition should not fall back to one-shot"
    assert art is not None


def test_decomposition_emits_start_and_complete_events(monkeypatch):
    """The SSE chip stream needs a marker for the decomposition branch —
    otherwise the user has no idea why the streaming raw-count events
    stopped (they never appear on the decomposition path; per-unit
    events replace them)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Silence the actor-critic loop so we're testing the branching, not
    # the critic behavior.
    monkeypatch.setenv("FORGE_SMITH_PLANNER_CRITIC", "0")
    events: list[tuple[str, dict]] = []

    def _emit(stage: str, payload: dict) -> None:
        events.append((stage, payload))

    with patch(
        "services.app_decomposition.should_decompose", return_value=True,
    ), patch(
        "agents.app_map_agent.run_app_map_planner", return_value=_plan_shape(),
    ), patch(
        "services.per_unit_authoring.author_all_units_async",
        side_effect=_fake_units,
    ):
        asyncio.run(orchestrate_planner(
            description="big",
            output_dir="/tmp/test-emit",
            emit_fn=_emit,
        ))

    stages = [s for s, _ in events]
    assert "planner_decompose_start" in stages
    assert "planner_decompose_complete" in stages
