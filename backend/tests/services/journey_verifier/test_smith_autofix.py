"""Unit tests for the V&F 2.0 Smith dispatcher (M2).

Covers ``smith_autofix.dispatch`` / ``dispatch_all`` and the
convergence helper ``mark_healed_faults``. Smith itself is stubbed
via the ``smith_runner=`` dependency-injection seam so tests don't
hit the LLM (or even import agents.smith_agent).

Verified:
  * TOOL_SUBSETS covers all three smith seams
  * dispatch() with a stub Smith returns a DispatchResult
  * dispatch_all() respects priority order (render-error first)
  * dispatch_all() respects run_budget: overflow → budget-exhausted residuals
  * mark_healed_faults matches by interaction_id, partitions correctly
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from services.journey_verifier.autofix import DispatchResult
from services.journey_verifier.fault_classifier import ClassifiedFault
from services.journey_verifier.smith_autofix import (
    TOOL_SUBSETS,
    _fault_priority,
    build_smith_prompt,
    dispatch,
    dispatch_all,
)
from services.journey_verifier.smith_autofix_convergence import (
    mark_healed_faults,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _cf(
    *,
    class_name: str = "render-error",
    seam: str = "smith:render",
    route: str = "/x",
    interaction_id: str | None = None,
) -> ClassifiedFault:
    iid = interaction_id or f"i:{route}:{class_name}"
    return ClassifiedFault(
        interaction_id=iid,
        route=route,
        class_name=class_name,
        seam=seam,
        evidence_slice="test",
        needed_context=[],
        raw={"interaction": {"id": iid, "route": route}, "evidence": {}},
    )


def _make_stub_runner(
    *,
    edited_paths: list[str] | None = None,
    trace_len: int = 1,
    raise_exc: BaseException | None = None,
    record: list[dict] | None = None,
):
    """Return an async fn that mimics run_smith_agent's contract.

    Each call appends to `record` (if provided) so tests can inspect
    ordering + args.
    """
    async def _runner(**kwargs: Any) -> dict[str, Any]:
        if record is not None:
            record.append(dict(kwargs))
        if raise_exc is not None:
            raise raise_exc
        return {
            "edited_paths": list(edited_paths or []),
            "trace": [{"tool": "edit_page", "result_summary": "ok"}] * trace_len,
            "answer": None,
            "diagnosis": None,
            "question": None,
            "handoff": None,
        }
    return _runner


# ── TOOL_SUBSETS ────────────────────────────────────────────────────────────


def test_tool_subsets_covers_all_smith_seams():
    assert set(TOOL_SUBSETS.keys()) == {
        "smith:render", "smith:binding", "smith:data-fetch",
    }
    # Every subset is non-empty
    for seam, tools in TOOL_SUBSETS.items():
        assert isinstance(tools, list) and tools, f"{seam} has empty subset"


# ── dispatch (single fault) ─────────────────────────────────────────────────


def test_dispatch_returns_dispatch_result(tmp_path: Path):
    stub = _make_stub_runner(
        edited_paths=["src/schemas/x.json"],
        trace_len=2,
    )
    result = asyncio.run(dispatch(
        _cf(class_name="render-error", seam="smith:render", route="/x"),
        tmp_path, smith_runner=stub,
    ))
    assert isinstance(result, DispatchResult)
    assert result.seam == "smith:render"
    assert result.class_name == "render-error"
    assert result.files_touched == ["src/schemas/x.json"]
    assert result.smith_turns_used == 2
    assert result.fixed is True
    assert result.ok is True


def test_dispatch_no_edits_reports_unfixed(tmp_path: Path):
    stub = _make_stub_runner(edited_paths=[], trace_len=1)
    result = asyncio.run(dispatch(
        _cf(class_name="binding-crash", seam="smith:binding", route="/y"),
        tmp_path, smith_runner=stub,
    ))
    assert result.fixed is False
    assert result.files_touched == []
    assert "no files written" in result.summary


def test_dispatch_crash_returns_error_result(tmp_path: Path):
    stub = _make_stub_runner(raise_exc=RuntimeError("smith exploded"))
    result = asyncio.run(dispatch(
        _cf(seam="smith:render"), tmp_path, smith_runner=stub,
    ))
    assert result.ok is False
    assert result.fixed is False
    assert "smith exploded" in (result.error or "")


def test_dispatch_passes_scoped_tools_and_turn_budget(tmp_path: Path):
    calls: list[dict] = []
    stub = _make_stub_runner(edited_paths=["a"], record=calls)
    asyncio.run(dispatch(
        _cf(seam="smith:data-fetch"), tmp_path,
        turn_budget=4, smith_runner=stub,
    ))
    assert calls, "runner should have been called"
    kwargs = calls[0]
    assert kwargs["scoped_tools"] == TOOL_SUBSETS["smith:data-fetch"]
    assert kwargs["turn_budget"] == 4
    assert "user_message" in kwargs and isinstance(kwargs["user_message"], str)


# ── dispatch_all — priority + budget ────────────────────────────────────────


def test_dispatch_all_priority_order(tmp_path: Path):
    """render-error dispatched before page-unresponsive even though both
    have seam smith:render."""
    order: list[str] = []

    async def runner(**kwargs: Any) -> dict[str, Any]:
        # Record the class from the prompt (rough — we embed 'Class: X'
        # into build_smith_prompt so we can pull it back out).
        prompt = kwargs.get("user_message", "")
        for cls in ("render-error", "binding-crash",
                    "data-fetch-failure", "page-unresponsive"):
            if f"Class: {cls}" in prompt:
                order.append(cls)
                break
        return {"edited_paths": [f"file-{len(order)}.tsx"], "trace": [{}]}

    faults = [
        _cf(class_name="page-unresponsive", seam="smith:render", route="/u"),
        _cf(class_name="data-fetch-failure", seam="smith:data-fetch", route="/d"),
        _cf(class_name="binding-crash", seam="smith:binding", route="/b"),
        _cf(class_name="render-error", seam="smith:render", route="/r"),
    ]
    asyncio.run(dispatch_all(faults, tmp_path, smith_runner=runner, run_budget=100))
    assert order == [
        "render-error", "binding-crash",
        "data-fetch-failure", "page-unresponsive",
    ]


def test_dispatch_all_respects_run_budget(tmp_path: Path):
    """When run_budget is exhausted, remaining faults come back as
    budget-exhausted residuals."""
    stub = _make_stub_runner(edited_paths=["x"], trace_len=3)
    # 3 faults × 3 turns = 9 turns needed. Cap at 5 turns.
    faults = [
        _cf(class_name="render-error", seam="smith:render", route=f"/r{i}",
            interaction_id=f"r{i}")
        for i in range(3)
    ]
    results = asyncio.run(dispatch_all(
        faults, tmp_path, smith_runner=stub,
        run_budget=5, turn_budget=3,
    ))
    assert len(results) == 3
    # First fault: 3 turns used (full budget). Second: 2 remaining (capped).
    # Third: 0 remaining → budget-exhausted residual.
    assert results[0].smith_turns_used == 3
    assert results[1].smith_turns_used == 2   # cap → dispatch cap = min(3, 2)
    assert results[2].error == "budget-exhausted"
    assert results[2].fixed is False
    assert results[2].smith_turns_used == 0


def test_dispatch_all_non_smith_seam_skipped(tmp_path: Path):
    stub = _make_stub_runner(edited_paths=["a"])
    fault = _cf(class_name="missing-page", seam="deterministic:add-page")
    results = asyncio.run(dispatch_all([fault], tmp_path, smith_runner=stub))
    assert len(results) == 1
    assert results[0].ran is False
    assert results[0].smith_turns_used == 0


def test_dispatch_all_empty_input(tmp_path: Path):
    results = asyncio.run(dispatch_all([], tmp_path))
    assert results == []


# ── _fault_priority helper ─────────────────────────────────────────────────


def test_fault_priority_ordering():
    a = _cf(class_name="render-error", seam="smith:render")
    b = _cf(class_name="binding-crash", seam="smith:binding")
    c = _cf(class_name="data-fetch-failure", seam="smith:data-fetch")
    d = _cf(class_name="page-unresponsive", seam="smith:render")
    ordered = sorted([d, c, b, a], key=_fault_priority)
    assert [f.class_name for f in ordered] == [
        "render-error", "binding-crash",
        "data-fetch-failure", "page-unresponsive",
    ]


# ── build_smith_prompt ─────────────────────────────────────────────────────


def test_build_smith_prompt_contains_all_sections(tmp_path: Path):
    from services.journey_verifier.fault_context import build_fault_context

    fault = _cf(seam="smith:render", class_name="render-error", route="/x")
    ctx = build_fault_context(fault, tmp_path)
    prompt = build_smith_prompt(fault, ctx, turn_budget=3)
    for header in (
        "OBSERVED SYMPTOM", "CONSOLE ERRORS", "NETWORK FAILURES",
        "RELATED ENTITIES", "RECENT EDITS TO THIS APP",
        "PAGE SCHEMA", "PAGE CODE", "TOOLS AVAILABLE TO YOU", "TASK",
        "Turn budget: 3",
    ):
        assert header in prompt, f"missing section: {header}"


# ── mark_healed_faults ─────────────────────────────────────────────────────


def test_mark_healed_faults_partitions_by_interaction_id():
    r1 = [
        _cf(interaction_id="a"),
        _cf(interaction_id="b"),
        _cf(interaction_id="c"),
    ]
    r2_faults = [
        {"interaction": {"id": "b"}, "passed": False},
        # a and c are absent → healed.
    ]
    healed, still = mark_healed_faults(r1, r2_faults)
    assert [f.interaction_id for f in healed] == ["a", "c"]
    assert [f.interaction_id for f in still] == ["b"]


def test_mark_healed_faults_treats_passed_true_as_healed():
    r1 = [_cf(interaction_id="a")]
    r2_faults = [{"interaction": {"id": "a"}, "passed": True}]
    healed, still = mark_healed_faults(r1, r2_faults)
    assert [f.interaction_id for f in healed] == ["a"]
    assert still == []


def test_mark_healed_faults_empty_round1():
    assert mark_healed_faults([], [{"interaction": {"id": "a"}}]) == ([], [])


def test_mark_healed_faults_empty_round2_all_healed():
    r1 = [_cf(interaction_id="a"), _cf(interaction_id="b")]
    healed, still = mark_healed_faults(r1, [])
    assert [f.interaction_id for f in healed] == ["a", "b"]
    assert still == []


def test_mark_healed_faults_unknown_id_stays_broken():
    """A round-1 fault with no matchable interaction_id can't be marked
    healed reliably — it stays in still_broken."""
    r1 = [ClassifiedFault(
        interaction_id="?",
        route="/x", class_name="render-error", seam="smith:render",
        evidence_slice="", needed_context=[], raw=None,
    )]
    healed, still = mark_healed_faults(r1, [])
    assert healed == []
    assert len(still) == 1


# ── apply_autofix_v2 integration (smith seams routed to dispatcher) ────────


def test_apply_autofix_v2_dispatches_smith_faults(tmp_path: Path, monkeypatch):
    """A raw 500 fault (render-error) triggers a Smith dispatch call."""
    from services.journey_verifier import autofix as autofix_mod
    from services.journey_verifier import smith_autofix as sa_mod

    calls: list[dict] = []

    async def stub_runner(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"edited_paths": ["src/x.tsx"], "trace": [{"tool": "edit_page"}]}

    monkeypatch.setattr(sa_mod, "_default_smith_runner", stub_runner)

    raw_faults = [{
        "id": "route:/x",
        "interaction": {"id": "route:/x", "route": "/x", "kind": "route"},
        "evidence": {"status": 500, "stack_trace": "Error: boom"},
    }]
    report = asyncio.run(autofix_mod.apply_autofix_v2(tmp_path, raw_faults))
    assert len(report.smith_results) == 1
    assert report.smith_results[0].class_name == "render-error"
    assert report.smith_results[0].fixed is True
    assert calls, "smith runner should have been called"


def test_apply_autofix_v2_sync_wrapper(tmp_path: Path, monkeypatch):
    from services.journey_verifier import autofix as autofix_mod
    from services.journey_verifier import smith_autofix as sa_mod

    async def stub_runner(**kwargs: Any) -> dict[str, Any]:
        return {"edited_paths": [], "trace": []}
    monkeypatch.setattr(sa_mod, "_default_smith_runner", stub_runner)

    raw_faults = [{
        "interaction": {"id": "i", "route": "/x", "kind": "route"},
        "evidence": {"status": 500},
    }]
    report = autofix_mod.apply_autofix_v2_sync(tmp_path, raw_faults)
    # 1 smith result (render-error), no deterministic
    assert len(report.smith_results) == 1
    assert len(report.deterministic_results) == 0
