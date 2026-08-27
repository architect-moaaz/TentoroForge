"""Tests for services.apply_signature_moves + services.signature_moves.

Spec C2 — registry-driven brief signature moves applied to page schemas.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import signature_moves
from services.apply_signature_moves import (
    apply_signature_moves,
    is_enabled,
)


# ────────────────────────────────────────────────────────────
# Registry
# ────────────────────────────────────────────────────────────

class TestRegistry:
    def test_known_kinds_includes_ledger_row(self):
        assert "ledger_row" in signature_moves.known_kinds()

    def test_registered_moves_have_descriptions(self):
        for entry in signature_moves.describe_all():
            assert entry["kind"]
            assert entry["description"]  # non-empty prompt copy

    def test_register_overwrites(self):
        # Register a stub, then re-register — last wins.
        signature_moves.register("__test_stub__", lambda n, c: True,
                                 lambda n, c: n, "v1")
        assert signature_moves.get("__test_stub__").description == "v1"
        signature_moves.register("__test_stub__", lambda n, c: True,
                                 lambda n, c: n, "v2")
        assert signature_moves.get("__test_stub__").description == "v2"

    def test_get_missing_returns_none(self):
        assert signature_moves.get("__not_a_kind__") is None


# ────────────────────────────────────────────────────────────
# Flag
# ────────────────────────────────────────────────────────────

class TestFlag:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("FORGE_POLISH_SIGNATURE_MOVES", raising=False)
        assert is_enabled() is False

    def test_on_when_truthy(self, monkeypatch):
        for v in ("1", "true", "yes", "on"):
            monkeypatch.setenv("FORGE_POLISH_SIGNATURE_MOVES", v)
            assert is_enabled() is True


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

def _write_page(tmp: Path, rel: str, page: dict) -> Path:
    p = tmp / "src" / "schemas" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(page), encoding="utf-8")
    return p


def _brief_with(*kinds: str) -> dict:
    return {
        "identity": {"domain": "T", "register": ["a"], "voice": "warm_precise",
                     "modes": ["light"]},
        "palette": {"brand": "#000", "accent": "#111", "neutrals_base": "#F0F0F0",
                    "neutrals_tint": "cool", "surface_bg": "#FFF",
                    "surface_elevated": "#FFF", "foreground_primary": "#000",
                    "foreground_muted": "#666"},
        "typography": {"display_family": "X", "body_family": "X"},
        "layout": {"density": "compact", "radius": "sharp_2"},
        "signature_moves": [{"kind": k, "detail": ""} for k in kinds],
    }


# ────────────────────────────────────────────────────────────
# Applying moves
# ────────────────────────────────────────────────────────────

class TestApply:
    def test_ledger_row_adds_row_style_to_tables(self, tmp_path):
        p = _write_page(tmp_path, "leases/index.json", {
            "route": "/leases",
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"columns": [{"field": "id"}, {"field": "name"}]}},
            ]},
        })
        res = apply_signature_moves(str(tmp_path), brief=_brief_with("ledger_row"))
        assert res["moves_applied"] == 1
        assert res["files"] == 1
        after = json.loads(p.read_text())
        table = after["root"]["children"][0]
        assert "borderLeft" in table["props"]["rowStyle"]

    def test_status_stripe_only_applies_to_tables_with_status_column(self, tmp_path):
        # Two tables — one has status column, one doesn't.
        _write_page(tmp_path, "a.json", {
            "route": "/a",
            "root": {"type": "Table", "props": {"columns": [{"field": "status"}]}},
        })
        _write_page(tmp_path, "b.json", {
            "route": "/b",
            "root": {"type": "Table", "props": {"columns": [{"field": "name"}]}},
        })
        res = apply_signature_moves(str(tmp_path), brief=_brief_with("status_stripe"))
        # Exactly one match — the status-carrying table.
        assert res["moves_applied"] == 1

    def test_keyline_breadcrumb_applies_to_h1_only(self, tmp_path):
        p = _write_page(tmp_path, "x.json", {
            "route": "/x",
            "root": {"type": "Stack", "children": [
                {"type": "Heading", "props": {"level": 1, "text": "Title"}},
                {"type": "Heading", "props": {"level": 2, "text": "Sub"}},
            ]},
        })
        res = apply_signature_moves(str(tmp_path), brief=_brief_with("keyline_breadcrumb"))
        assert res["moves_applied"] == 1
        after = json.loads(p.read_text())
        h1 = after["root"]["children"][0]
        h2 = after["root"]["children"][1]
        assert "borderBottom" in h1["props"]["style"]
        assert "style" not in h2.get("props", {})

    def test_velocity_sparkline_targets_stats(self, tmp_path):
        _write_page(tmp_path, "dash.json", {
            "route": "/",
            "root": {"type": "Grid", "children": [
                {"type": "Stat", "props": {"label": "Units"}},
                {"type": "Stat", "props": {"label": "Rent"}},
                {"type": "Table", "props": {"columns": [{"field": "id"}]}},
            ]},
        })
        res = apply_signature_moves(str(tmp_path), brief=_brief_with("velocity_sparkline"))
        # Only the 2 Stats.
        assert res["moves_applied"] == 2

    def test_multiple_moves_compose(self, tmp_path):
        _write_page(tmp_path, "dash.json", {
            "route": "/",
            "root": {"type": "Stack", "children": [
                {"type": "Heading", "props": {"level": 1, "text": "Home"}},
                {"type": "Stat", "props": {"label": "N"}},
                {"type": "Table", "props": {"columns": [{"field": "status"}]}},
            ]},
        })
        res = apply_signature_moves(
            str(tmp_path),
            brief=_brief_with("keyline_breadcrumb", "velocity_sparkline",
                              "status_stripe", "ledger_row"),
        )
        # keyline(1) + sparkline(1) + status_stripe(1) + ledger_row(1) = 4.
        assert res["moves_applied"] == 4


# ────────────────────────────────────────────────────────────
# Failure paths — spec: never crash, always logged
# ────────────────────────────────────────────────────────────

class TestFailureModes:
    def test_unknown_kind_logged_and_reported(self, tmp_path):
        _write_page(tmp_path, "x.json", {
            "route": "/x", "root": {"type": "Table",
                                     "props": {"columns": [{"field": "id"}]}},
        })
        res = apply_signature_moves(str(tmp_path),
                                    brief=_brief_with("nonexistent_move"))
        assert res["moves_applied"] == 0
        assert res["unknown_kinds"] == ["nonexistent_move"]

    def test_missing_dir_safe(self, tmp_path):
        res = apply_signature_moves(str(tmp_path / "ghost"),
                                    brief=_brief_with("ledger_row"))
        assert res == {"moves_applied": 0, "nodes_touched": 0,
                       "files": 0, "unknown_kinds": []}

    def test_no_brief_no_op(self, tmp_path):
        _write_page(tmp_path, "x.json", {"route": "/x", "root": {"type": "Table"}})
        res = apply_signature_moves(str(tmp_path), brief=None)
        assert res["moves_applied"] == 0

    def test_empty_moves_no_op(self, tmp_path):
        _write_page(tmp_path, "x.json", {"route": "/x", "root": {"type": "Table"}})
        res = apply_signature_moves(str(tmp_path), brief=_brief_with())
        assert res["moves_applied"] == 0

    def test_shell_and_navflow_skipped(self, tmp_path):
        _write_page(tmp_path, "shell.json", {
            "root": {"type": "Table", "props": {"columns": [{"field": "id"}]}},
        })
        res = apply_signature_moves(str(tmp_path), brief=_brief_with("ledger_row"))
        assert res["moves_applied"] == 0


# ────────────────────────────────────────────────────────────
# Idempotency
# ────────────────────────────────────────────────────────────

class TestIdempotent:
    def test_second_run_produces_same_output(self, tmp_path):
        p = _write_page(tmp_path, "x.json", {
            "route": "/x",
            "root": {"type": "Table", "props": {"columns": [{"field": "id"}]}},
        })
        brief = _brief_with("ledger_row")
        apply_signature_moves(str(tmp_path), brief=brief)
        first = p.read_text()
        apply_signature_moves(str(tmp_path), brief=brief)
        second = p.read_text()
        assert first == second
