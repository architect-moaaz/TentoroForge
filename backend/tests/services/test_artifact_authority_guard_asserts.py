"""Tests for the Phase 6-5 guard demotions on collection + record schemas.

Guards covered:
- surface_wrap_guard.wrap_bare_data_displays (already dashboard-aware;
  extended in P6 to honor collection + record composer markers)
- list_data_source_guard.reconcile_list_sources
- table_row_nav_guard.guard_table_row_nav
- singleton_page_reconciler.reconcile_singleton_pages
- submit_authority_guards.form_target_guard
- workflow_trigger_button_guard.neutralize_event_only_buttons
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.chart_data_source_guard import guard_chart_data_sources
from services.list_data_source_guard import reconcile_list_sources
from services.singleton_page_reconciler import reconcile_singleton_pages
from services.submit_authority_guards import form_target_guard
from services.surface_wrap_guard import wrap_bare_data_displays
from services.table_row_nav_guard import guard_table_row_nav
from services.workflow_trigger_button_guard import neutralize_event_only_buttons


def _write_schema(root: Path, slug: str, doc: dict) -> Path:
    p = root / "src" / "schemas" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _write_plan(root: Path, pages: list[dict], entities: dict | None = None) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "plan.json").write_text(
        json.dumps({"pages": pages, "entities": entities or {}}),
        encoding="utf-8",
    )


def _collection_marker(schema: dict) -> dict:
    schema.setdefault("meta", {})["collection_maquette_composed"] = True
    return schema


def _record_marker(schema: dict) -> dict:
    schema.setdefault("meta", {})["record_maquette_composed"] = True
    return schema


# ─────────────────────────── surface_wrap_guard (cross-artifact) ──────


class TestSurfaceWrapCrossArtifact:
    def test_collection_marker_and_flag_asserts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        schema = _collection_marker({
            "id": "list", "route": "/list",
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"columns": [], "rows": []}},
            ]},
        })
        p = _write_schema(tmp_path, "list", schema)
        before = p.read_text()
        result = wrap_bare_data_displays(str(tmp_path))
        assert result["wrapped"] == 0
        assert result["asserts_logged"] == 1
        assert p.read_text() == before

    def test_record_marker_and_flag_asserts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        schema = _record_marker({
            "id": "form", "route": "/form",
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"columns": [], "rows": []}},
            ]},
        })
        p = _write_schema(tmp_path, "form", schema)
        result = wrap_bare_data_displays(str(tmp_path))
        assert result["asserts_logged"] == 1

    def test_collection_marker_without_flag_still_rewrites(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        schema = _collection_marker({
            "id": "list", "route": "/list",
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"columns": [], "rows": []}},
            ]},
        })
        _write_schema(tmp_path, "list", schema)
        result = wrap_bare_data_displays(str(tmp_path))
        # Marker alone doesn't stop legacy behaviour — flag must be on too.
        assert result["wrapped"] > 0
        assert result["asserts_logged"] == 0


# ─────────────────────────── list_data_source_guard ───────────────────


class TestListDataSourceGuard:
    def test_flag_on_marker_asserts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        schema = _collection_marker({
            "id": "list", "route": "/list",
            "dataSources": [{"name": "nonexistent_bad", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"rows": "{{nonexistent_bad}}"}},
            ]},
        })
        p = _write_schema(tmp_path, "list", schema)
        before = p.read_text()
        result = reconcile_list_sources(str(tmp_path))
        assert result["asserts_logged"] == 1
        # No mutation.
        assert p.read_text() == before

    def test_flag_off_marker_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        _collection_marker({})  # marker only meaningful with the flag
        result = reconcile_list_sources(str(tmp_path))
        assert result.get("asserts_logged", 0) == 0


# ─────────────────────────── table_row_nav_guard ──────────────────────


class TestTableRowNavGuard:
    def test_flag_on_marker_asserts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        schema = _collection_marker({
            "id": "sessions", "route": "/sessions",
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"columns": [], "rows": []}},
            ]},
        })
        p = _write_schema(tmp_path, "sessions", schema)
        before = p.read_text()
        result = guard_table_row_nav(str(tmp_path))
        assert result["asserts_logged"] == 1
        assert p.read_text() == before

    def test_flag_off_still_wires(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        # Same schema — no marker check under legacy path.
        _collection_marker({"id": "sessions"})
        result = guard_table_row_nav(str(tmp_path))
        assert result.get("asserts_logged", 0) == 0


# ─────────────────────────── singleton_page_reconciler ────────────────


class TestSingletonPageReconciler:
    def test_record_authority_does_not_disable_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """This pass used to no-op under record authority, on the claim that
        the composer's tail-fill made it redundant. It doesn't: the composer
        fills routes listed in the PLAN and never reads ``nav-flow.json``,
        while this reconciler exists to catch routes the LLM *linked to* and
        nobody emitted. Skipping it lost ``/profile`` + ``/profile/edit``.

        It also cannot race the composer — synthesis is skipped for any
        route whose file already exists.
        """
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        result = reconcile_singleton_pages(str(tmp_path))
        assert result.get("asserts_logged", 0) == 0

    def test_flag_off_runs_legacy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")
        result = reconcile_singleton_pages(str(tmp_path))
        assert result.get("asserts_logged", 0) == 0


# ─────────────────────────── form_target_guard ────────────────────────


class TestFormTargetGuard:
    def test_flag_on_marker_composer_authored_skips_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        # Form without workflow prop — legacy would flag it. Composer marker
        # + flag → this is the composer's decision, so no violation.
        schema = _record_marker({
            "id": "new", "route": "/bookings/new",
            "root": {"type": "Form", "props": {}, "children": []},
        })
        _write_schema(tmp_path, "bookings/new", schema)
        _write_plan(tmp_path, [{"route": "/bookings/new", "type": "form", "entity": "bookings"}])
        result = form_target_guard(str(tmp_path))
        # No violations logged for the composer-authored page.
        assert result["ok"] is True
        assert result["violations"] == []

    def test_flag_off_marker_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        schema = _record_marker({
            "id": "new", "route": "/bookings/new",
            "root": {"type": "Form", "props": {}, "children": []},
        })
        _write_schema(tmp_path, "bookings/new", schema)
        _write_plan(tmp_path, [{"route": "/bookings/new", "type": "form", "entity": "bookings"}])
        result = form_target_guard(str(tmp_path))
        # Legacy path: same schema DOES flag a violation.
        assert result["ok"] is False


# ─────────────────────────── workflow_trigger_button_guard ────────────


class TestWorkflowTriggerButtonGuard:
    def test_flag_on_marker_asserts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "1")
        # Need a workflows dir so the trigger index isn't empty (which
        # would short-circuit before the marker-check code path).
        (tmp_path / "workflows").mkdir(parents=True, exist_ok=True)
        (tmp_path / "workflows" / "sample.json").write_text(
            json.dumps({"id": "sample", "trigger": {"type": "event"}}),
            encoding="utf-8",
        )
        schema = _record_marker({
            "id": "detail", "route": "/bookings/[id]",
            "root": {"type": "Button", "props": {"workflow": "sample"}},
        })
        p = _write_schema(tmp_path, "bookings/[id]", schema)
        before = p.read_text()
        result = neutralize_event_only_buttons(str(tmp_path))
        assert result["asserts_logged"] >= 1
        assert p.read_text() == before

    def test_flag_off_marker_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")  # explicit opt-out: absent now means ON
        (tmp_path / "workflows").mkdir(parents=True, exist_ok=True)
        (tmp_path / "workflows" / "sample.json").write_text(
            json.dumps({"id": "sample", "trigger": {"type": "event"}}),
            encoding="utf-8",
        )
        _record_marker({"id": "x"})
        result = neutralize_event_only_buttons(str(tmp_path))
        assert result.get("asserts_logged", 0) == 0
