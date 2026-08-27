"""Tests for Phase 7 — post_gen_phases (guard counter + idempotency)."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from services.post_gen_phases import (
    PostGenPhase,
    _canonical,
    assert_guards_ran_once,
    is_run_complete,
    mark_run_complete,
    record_guard_run,
    reset_run,
    run_report,
)


@pytest.fixture(autouse=True)
def _clean_state(tmp_path):
    """Every test starts with the counter empty for tmp_path so runs in
    the same pytest process don't pollute each other."""
    reset_run(str(tmp_path))
    yield
    reset_run(str(tmp_path))


class TestReset:
    def test_reset_run_clears_counters(self, tmp_path):
        record_guard_run(str(tmp_path), "foo", PostGenPhase.SCHEMA_INTEGRITY)
        assert run_report(str(tmp_path)) == {"foo": 1}
        reset_run(str(tmp_path))
        assert run_report(str(tmp_path)) == {}

    def test_reset_run_clears_completed(self, tmp_path):
        mark_run_complete(str(tmp_path))
        assert is_run_complete(str(tmp_path))
        reset_run(str(tmp_path))
        assert not is_run_complete(str(tmp_path))

    def test_reset_run_scoped_to_output_dir(self, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        record_guard_run(str(tmp_path), "foo", PostGenPhase.SCHEMA_INTEGRITY)
        record_guard_run(str(other), "foo", PostGenPhase.SCHEMA_INTEGRITY)
        reset_run(str(tmp_path))
        assert run_report(str(tmp_path)) == {}
        assert run_report(str(other)) == {"foo": 1}
        reset_run(str(other))


class TestRecordGuardRun:
    def test_first_call_returns_1(self, tmp_path):
        assert record_guard_run(str(tmp_path), "foo", PostGenPhase.UI_POLISH) == 1

    def test_second_call_returns_2(self, tmp_path):
        record_guard_run(str(tmp_path), "foo", PostGenPhase.UI_POLISH)
        assert record_guard_run(str(tmp_path), "foo", PostGenPhase.UI_POLISH) == 2

    def test_duplicate_run_logs_warning(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="services.post_gen_phases"):
            record_guard_run(str(tmp_path), "form_scaffold", PostGenPhase.FORM_AUTHORING)
            record_guard_run(str(tmp_path), "form_scaffold", PostGenPhase.FORM_AUTHORING)
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "form_scaffold" in joined
        assert "ran 2 times" in joined
        assert "FORM_AUTHORING" in joined

    def test_first_call_does_not_warn(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="services.post_gen_phases"):
            record_guard_run(str(tmp_path), "solo", PostGenPhase.VALIDATION)
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_different_guards_do_not_conflict(self, tmp_path):
        record_guard_run(str(tmp_path), "a", PostGenPhase.SCHEMA_INTEGRITY)
        record_guard_run(str(tmp_path), "b", PostGenPhase.WORKFLOW_INTEGRITY)
        record_guard_run(str(tmp_path), "c", PostGenPhase.DB_INTEGRITY)
        assert run_report(str(tmp_path)) == {"a": 1, "b": 1, "c": 1}


class TestAssertGuardsRanOnce:
    def test_empty_when_nothing_ran(self, tmp_path):
        assert assert_guards_ran_once(str(tmp_path)) == []

    def test_empty_when_all_ran_once(self, tmp_path):
        record_guard_run(str(tmp_path), "a", PostGenPhase.SCHEMA_INTEGRITY)
        record_guard_run(str(tmp_path), "b", PostGenPhase.UI_POLISH)
        assert assert_guards_ran_once(str(tmp_path)) == []

    def test_lists_duplicates(self, tmp_path):
        record_guard_run(str(tmp_path), "clean", PostGenPhase.SCHEMA_INTEGRITY)
        record_guard_run(str(tmp_path), "dup", PostGenPhase.UI_POLISH)
        record_guard_run(str(tmp_path), "dup", PostGenPhase.UI_POLISH)
        assert assert_guards_ran_once(str(tmp_path)) == ["dup"]


class TestCanonicalization:
    def test_relative_and_absolute_share_counter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        record_guard_run(".", "foo", PostGenPhase.SCHEMA_INTEGRITY)
        # Absolute form should hit the same slot.
        assert record_guard_run(str(tmp_path.resolve()), "foo",
                                 PostGenPhase.SCHEMA_INTEGRITY) == 2

    def test_canonical_survives_path_object(self, tmp_path):
        p = Path(tmp_path)
        assert _canonical(p) == _canonical(str(tmp_path))


class TestCompletionMarker:
    def test_completion_marker_defaults_false(self, tmp_path):
        assert not is_run_complete(str(tmp_path))

    def test_mark_then_is_complete(self, tmp_path):
        mark_run_complete(str(tmp_path))
        assert is_run_complete(str(tmp_path))

    def test_reset_after_complete(self, tmp_path):
        mark_run_complete(str(tmp_path))
        reset_run(str(tmp_path))
        assert not is_run_complete(str(tmp_path))


class TestPhaseEnumStable:
    """Ordinals are load-bearing: several places sort by phase. If someone
    reorders the enum they should be forced to update tests."""

    def test_ordinal_order(self):
        assert PostGenPhase.SCHEMA_INTEGRITY < PostGenPhase.WORKFLOW_INTEGRITY
        assert PostGenPhase.WORKFLOW_INTEGRITY < PostGenPhase.DB_INTEGRITY
        assert PostGenPhase.DB_INTEGRITY < PostGenPhase.FORM_AUTHORING
        assert PostGenPhase.FORM_AUTHORING < PostGenPhase.PAGE_COMPOSITION
        assert PostGenPhase.PAGE_COMPOSITION < PostGenPhase.ROUTE_RECONCILIATION
        assert PostGenPhase.ROUTE_RECONCILIATION < PostGenPhase.UI_POLISH
        assert PostGenPhase.UI_POLISH < PostGenPhase.VALIDATION

    def test_all_eight_phases_present(self):
        assert len(PostGenPhase) == 8
