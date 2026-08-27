"""Tests for M5 batch — T2-lite (SessionContext ambient + persist) + T6
(stage_verify_ladder) + T7 (domain_conformance-driven verify) + T9
(read_last_verify_run surfaces session_history)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services import session_context as sc
from services import stage_verify_ladder as svl


# ══════════════════════════════════════════════════════════════════
# T2-lite — ambient SessionContext accessor
# ══════════════════════════════════════════════════════════════════


class TestAmbientSessionContext:
    def test_default_current_is_none(self):
        # In a fresh test, current() may be either None or something set
        # by a preceding test; force-reset via set_current(None).
        sc.set_current(None)
        assert sc.current() is None

    def test_set_and_reset(self):
        sc.set_current(None)
        ctx = sc.from_plan({"industry": "recruitment"})
        token = sc.set_current(ctx)
        assert sc.current() is ctx
        sc.reset_current(token)
        assert sc.current() is None

    def test_from_plan_captures_shape(self):
        ctx = sc.from_plan({"app_shape": {"layout": {"shell": "sidebar"}}})
        assert ctx.shape_profile["layout"]["shell"] == "sidebar"


# ══════════════════════════════════════════════════════════════════
# T2-lite — persist / load history
# ══════════════════════════════════════════════════════════════════


class TestPersistHistory:
    def test_persist_and_load_round_trip(self, tmp_path):
        ctx = sc.from_plan({"industry": "x"})
        ctx.record_verify(sc.VerifyRecord(
            stage="page_schema_agent",
            check="domain_conformance",
            passed=True,
            findings=[],
            duration_ms=12,
        ))
        ctx.record_edit(sc.EditRecord(
            stage="edit_page",
            intent="rename button",
            files_touched=["src/schemas/tasks.json"],
            reason="user asked",
        ))
        written = sc.persist_history(ctx, tmp_path)
        assert written is not None
        assert written.exists()

        loaded = sc.load_history(tmp_path)
        assert loaded is not None
        assert len(loaded["verify_history"]) == 1
        assert loaded["verify_history"][0]["stage"] == "page_schema_agent"
        assert loaded["edit_history"][0]["intent"] == "rename button"

    def test_load_absent_returns_none(self, tmp_path):
        assert sc.load_history(tmp_path) is None

    def test_load_malformed_returns_none(self, tmp_path):
        p = sc._history_path(tmp_path)
        p.parent.mkdir(parents=True)
        p.write_text("{not json", encoding="utf-8")
        assert sc.load_history(tmp_path) is None


# ══════════════════════════════════════════════════════════════════
# T6 + T7 — stage_verify_ladder + domain_conformance
# ══════════════════════════════════════════════════════════════════


def _snap2app_plan() -> dict:
    return {
        "app_shape": {
            "layout": {"shell": "none"},
            "nav": {"menu": "none"},
            "workflows": {"executionMode": "fire-and-forget"},
        },
    }


def _clean_scan_page() -> dict:
    return {
        "schemaVersion": "2",
        "id": "scan",
        "route": "/scan",
        "root": {"type": "Stack", "children": [
            {"type": "CameraCapture"},
            {"type": "Button", "props": {"label": "Scan"}},
        ]},
    }


def _dirty_scan_page_with_sidebar() -> dict:
    # Violates layout.shell=none — the Sidebar shouldn't be here.
    return {
        "schemaVersion": "2",
        "id": "scan",
        "route": "/scan",
        "root": {"type": "Stack", "children": [
            {"type": "Sidebar", "children": []},
            {"type": "CameraCapture"},
        ]},
    }


class TestLadderRecordOnlyMode:
    """Flag off (default): ladder ALWAYS returns success, no retries fire,
    but verify_history still gets a record so telemetry works."""

    def _install_ctx(self):
        sc.set_current(None)
        ctx = sc.from_plan(_snap2app_plan())
        sc.set_current(ctx)
        return ctx

    def test_flag_off_by_default(self, monkeypatch):
        monkeypatch.delenv("FORGE_RECOVER_LADDER", raising=False)
        assert svl.is_enabled() is False

    def test_record_only_success_on_clean_page(self, monkeypatch):
        monkeypatch.delenv("FORGE_RECOVER_LADDER", raising=False)
        ctx = self._install_ctx()
        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=_snap2app_plan(),
            route="/scan",
            attempt_1=lambda: _clean_scan_page(),
        )
        assert result.succeeded is True
        assert result.succeeding_rung == "llm_first"
        # verify_stack now records one entry per cheap check + aggregate
        assert any(v.stage == "page_schema_agent" for v in ctx.verify_history)
        agg = [v for v in ctx.verify_history if v.check == "aggregate"]
        assert agg and agg[0].passed is True
        sc.set_current(None)

    def test_record_only_success_even_when_dirty(self, monkeypatch):
        """Flag off: even when findings are present, ladder returns
        success (historic behavior preserved) but the record captures
        the finding for telemetry."""
        monkeypatch.delenv("FORGE_RECOVER_LADDER", raising=False)
        ctx = self._install_ctx()
        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=_snap2app_plan(),
            route="/scan",
            attempt_1=lambda: _dirty_scan_page_with_sidebar(),
        )
        assert result.succeeded is True
        # verify_stack records per-check entries; find the failing domain_conformance one
        dc = [v for v in ctx.verify_history if v.check == "domain_conformance"]
        assert dc and dc[0].passed is False
        assert any("shell_present_on_none" in (f.get("rule") or "")
                   for f in dc[0].findings)
        sc.set_current(None)


class TestLadderFlagOnFullBehavior:
    """Flag on: full ladder fires; retries + fallback are real."""

    def _install_ctx(self):
        sc.set_current(None)
        ctx = sc.from_plan(_snap2app_plan())
        sc.set_current(ctx)
        return ctx

    def test_clean_first_attempt_passes(self, monkeypatch):
        monkeypatch.setenv("FORGE_RECOVER_LADDER", "1")
        ctx = self._install_ctx()
        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=_snap2app_plan(),
            route="/scan",
            attempt_1=lambda: _clean_scan_page(),
        )
        assert result.succeeded is True
        assert result.succeeding_rung == "llm_first"
        # verify_history has one attempt record — the ladder's aggregate
        # (per-check records use the raw stage name; the ladder's
        # per-rung aggregate uses the ':llm_first' suffix)
        assert any(v.stage == "page_schema_agent:llm_first" for v in ctx.verify_history)
        sc.set_current(None)

    def test_second_rung_with_findings_succeeds(self, monkeypatch):
        monkeypatch.setenv("FORGE_RECOVER_LADDER", "1")
        ctx = self._install_ctx()

        def bad_first():
            return _dirty_scan_page_with_sidebar()

        captured_findings: list = []

        def retry_with(findings):
            captured_findings.extend(findings)
            return _clean_scan_page()

        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=_snap2app_plan(),
            route="/scan",
            attempt_1=bad_first,
            attempt_2_with_findings=retry_with,
        )
        assert result.succeeded is True
        assert result.succeeding_rung == "llm_with_findings"
        # Retry received the domain_conformance findings from attempt 1
        assert any("shell_present_on_none" in (f.get("rule") or "")
                   for f in captured_findings)
        # verify_history has two records: llm_first (failed) + llm_with_findings (passed)
        stages = [v.stage for v in ctx.verify_history]
        assert "page_schema_agent:llm_first" in stages
        assert "page_schema_agent:llm_with_findings" in stages
        sc.set_current(None)

    def test_fallback_rung_succeeds_when_llm_fails(self, monkeypatch):
        monkeypatch.setenv("FORGE_RECOVER_LADDER", "1")
        ctx = self._install_ctx()
        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=_snap2app_plan(),
            route="/scan",
            attempt_1=lambda: _dirty_scan_page_with_sidebar(),
            attempt_2_with_findings=lambda findings: _dirty_scan_page_with_sidebar(),
            template_fallback=lambda: _clean_scan_page(),
        )
        assert result.succeeded is True
        assert result.succeeding_rung == "template"
        sc.set_current(None)

    def test_all_rungs_fail_escalates(self, monkeypatch):
        monkeypatch.setenv("FORGE_RECOVER_LADDER", "1")
        ctx = self._install_ctx()
        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=_snap2app_plan(),
            route="/scan",
            attempt_1=lambda: _dirty_scan_page_with_sidebar(),
            attempt_2_with_findings=lambda f: _dirty_scan_page_with_sidebar(),
            template_fallback=lambda: _dirty_scan_page_with_sidebar(),
        )
        assert result.succeeded is False
        assert result.succeeding_rung is None
        # Escalation report is well-formed
        report = result.escalation_report()
        assert report["succeeded"] is False
        assert len(report["attempts"]) == 4  # llm_first + llm_with_findings + template + escalated
        sc.set_current(None)


class TestNoAmbientContext:
    """When no ambient SessionContext is set, ladder still works — it
    just skips the record step. Fixes the "empty context, ladder crashes"
    class permanently."""

    def test_no_context_still_returns_result(self, monkeypatch):
        monkeypatch.delenv("FORGE_RECOVER_LADDER", raising=False)
        sc.set_current(None)
        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=_snap2app_plan(),
            route="/scan",
            attempt_1=lambda: _clean_scan_page(),
        )
        assert result.succeeded is True

    def test_no_context_flag_on_still_works(self, monkeypatch):
        monkeypatch.setenv("FORGE_RECOVER_LADDER", "1")
        sc.set_current(None)
        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=_snap2app_plan(),
            route="/scan",
            attempt_1=lambda: _clean_scan_page(),
        )
        assert result.succeeded is True


# ══════════════════════════════════════════════════════════════════
# T9 — read_last_verify_run reads session_history when persisted
# ══════════════════════════════════════════════════════════════════


class TestReadLastVerifyRunHistory:
    """The T9 wiring in _smith_read_last_verify_run reads
    session_context.load_history from the resolved output_dir and
    attaches it to the returned payload as ``session_history``. We test
    the read half in isolation — the DB side needs an async session +
    project row, which is exercised elsewhere."""

    def test_load_history_from_persisted_run(self, tmp_path):
        # Simulate: pipeline ran, persisted history, then Smith wants to read.
        ctx = sc.from_plan({"industry": "recruitment"})
        ctx.record_verify(sc.VerifyRecord(
            stage="page_schema_agent:llm_first",
            check="domain_conformance",
            passed=False,
            findings=[{"rule": "domain_conformance.shell_present_on_none",
                       "message": "Sidebar found on shell:none route",
                       "severity": "error"}],
            duration_ms=42,
        ))
        ctx.record_verify(sc.VerifyRecord(
            stage="page_schema_agent:llm_with_findings",
            check="domain_conformance",
            passed=True,
            findings=[],
            duration_ms=38,
        ))
        sc.persist_history(ctx, tmp_path)

        loaded = sc.load_history(tmp_path)
        assert loaded is not None
        assert len(loaded["verify_history"]) == 2
        # Most-recent-first ordering preserved
        assert loaded["verify_history"][0]["stage"].endswith("llm_with_findings")
        assert loaded["verify_history"][1]["stage"].endswith("llm_first")
        # Findings survived the round-trip
        finding = loaded["verify_history"][1]["findings"][0]
        assert finding["rule"] == "domain_conformance.shell_present_on_none"
