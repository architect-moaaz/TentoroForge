"""Unit tests for the journey-verifier auto-fix dispatcher.

Handler modules are monkeypatched so we don't hit any real file I/O or
seam side effects — we only care that the dispatcher routes each
target_seam to the right handler, dedups, and preserves residuals.
"""
from __future__ import annotations

from services.journey_verifier import autofix as autofix_mod
from services.journey_verifier.autofix import (
    DispatchResult,
    apply_autofix,
)


def _hint(seam: str, slug: str = "j") -> dict:
    return {
        "journey_slug": slug,
        "failing_step": "something",
        "likely_cause": "x",
        "target_seam": seam,
        "hint": "do the thing",
        "tags": [],
    }


def test_empty_hints_returns_empty_report():
    report = apply_autofix("/tmp", [])
    assert report.dispatched == []
    assert report.residual_hints == []
    assert report.skipped_seams == []


def test_dispatches_one_handler_per_seam(monkeypatch, tmp_path):
    calls: list[str] = []
    def stub(seam: str):
        def h(_dir):
            calls.append(seam)
            return DispatchResult(seam=seam, ran=True, summary=f"{seam} ran")
        return h
    for seam in ["workflow-definition", "workflow-output-mapping", "auth-seed"]:
        monkeypatch.setitem(autofix_mod._SEAM_HANDLERS, seam, stub(seam))

    report = apply_autofix(tmp_path, [
        _hint("workflow-definition", "a"),
        _hint("workflow-output-mapping", "b"),
        _hint("auth-seed", "c"),
    ])
    assert set(calls) == {"workflow-definition", "workflow-output-mapping", "auth-seed"}
    assert len(report.dispatched) == 3


def test_dedups_same_seam(monkeypatch, tmp_path):
    calls: list[str] = []
    def h(_dir):
        calls.append("wf")
        return DispatchResult(seam="workflow-definition", ran=True, summary="ran once")
    monkeypatch.setitem(autofix_mod._SEAM_HANDLERS, "workflow-definition", h)

    report = apply_autofix(tmp_path, [
        _hint("workflow-definition", "a"),
        _hint("workflow-definition", "b"),
        _hint("workflow-definition", "c"),
    ])
    # Same seam thrice → one dispatch, three hints.
    assert calls == ["wf"]
    assert len(report.dispatched) == 1


def test_unknown_seam_lands_in_residual(tmp_path):
    report = apply_autofix(tmp_path, [_hint("unknown", "a")])
    assert report.dispatched == []
    assert len(report.residual_hints) == 1
    assert report.residual_hints[0]["target_seam"] == "unknown"


def test_seam_without_handler_becomes_residual(monkeypatch, tmp_path):
    # Clear the table so nothing has a handler.
    monkeypatch.setattr(autofix_mod, "_SEAM_HANDLERS", {})
    report = apply_autofix(tmp_path, [_hint("some-new-seam", "a")])
    assert "some-new-seam" in report.skipped_seams
    assert len(report.residual_hints) == 1


def test_handler_failure_still_records_dispatch(monkeypatch, tmp_path):
    def failing_h(_dir):
        return DispatchResult(
            seam="workflow-definition", ran=True, ok=False,
            summary="oops", error="boom",
        )
    monkeypatch.setitem(autofix_mod._SEAM_HANDLERS, "workflow-definition", failing_h)
    report = apply_autofix(tmp_path, [_hint("workflow-definition")])
    assert len(report.dispatched) == 1
    assert report.dispatched[0].ok is False


def test_report_serializes_to_dict(tmp_path):
    report = apply_autofix(tmp_path, [_hint("unknown", "a")])
    d = report.to_dict()
    assert "dispatched" in d
    assert "residual_hints" in d
    assert "skipped_seams" in d
    assert isinstance(d["residual_hints"], list)
