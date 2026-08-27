"""Tests for services.navigate_target_guard (B-022.8 root fix)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.navigate_target_guard import apply_navigate_target_guard


def _make_app(root: Path, *, plan: dict, schemas: dict[str, dict]) -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))
    for name, doc in schemas.items():
        (root / "src" / "schemas" / f"{name}.json").write_text(json.dumps(doc))


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "src" / "schemas" / f"{name}.json").read_text())


# ---------- known routes are left alone -----------------------------------

class TestKnownTargetsUntouched:
    def test_exact_match_static_route(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "pages": [{"route": "/plants"}, {"route": "/orders"}],
        }, schemas={"orders": {
            "nodes": [{"type": "Button", "props": {"text": "View plants", "navigate": "/plants"}}]
        }})
        r = apply_navigate_target_guard(str(tmp_path))
        assert r["repaired"] == []
        assert r["marked"] == []
        after = _read(tmp_path, "orders")
        assert after["nodes"][0]["props"]["navigate"] == "/plants"

    def test_dynamic_segment_match(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "pages": [{"route": "/plants"}, {"route": "/plants/[id]"}],
        }, schemas={"plants": {
            "nodes": [{"type": "Button", "props": {"navigate": "/plants/abc-uuid-42"}}]
        }})
        r = apply_navigate_target_guard(str(tmp_path))
        assert r["repaired"] == []
        assert r["marked"] == []

    def test_dynamic_binding_passthrough(self, tmp_path: Path):
        """A navigate value with `{{...}}` is resolved at runtime — leave it."""
        _make_app(tmp_path, plan={
            "pages": [{"route": "/orders"}],
        }, schemas={"orders": {
            "nodes": [{"type": "Button", "props": {"navigate": "/anywhere/{{row.id}}"}}]
        }})
        r = apply_navigate_target_guard(str(tmp_path))
        assert r["repaired"] == []
        assert r["marked"] == []

    def test_external_url_passthrough(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "pages": [{"route": "/orders"}],
        }, schemas={"orders": {
            "nodes": [{"type": "Button", "props": {"navigate": "https://external.example/help"}}]
        }})
        r = apply_navigate_target_guard(str(tmp_path))
        assert r["repaired"] == []
        assert r["marked"] == []


# ---------- broken targets get repaired or marked -------------------------

class TestBrokenTargets:
    def test_nearest_prefix_repair(self, tmp_path: Path):
        """Nav target `/favourites/details/abc` when only `/favourites` exists
        should collapse to `/favourites` (safe fallback)."""
        _make_app(tmp_path, plan={
            "pages": [{"route": "/favourites"}],
        }, schemas={"favourites": {
            "nodes": [{"type": "Button", "props": {"text": "View details", "navigate": "/favourites/details/abc"}}]
        }})
        r = apply_navigate_target_guard(str(tmp_path))
        assert len(r["repaired"]) == 1
        assert r["repaired"][0]["was"] == "/favourites/details/abc"
        assert r["repaired"][0]["now"] == "/favourites"

    def test_marks_when_no_repair_available(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "pages": [{"route": "/orders"}],
        }, schemas={"orders": {
            "nodes": [{"type": "Button", "props": {"text": "??", "navigate": "/something-else"}}]
        }})
        r = apply_navigate_target_guard(str(tmp_path))
        assert len(r["marked"]) == 1
        after = _read(tmp_path, "orders")
        assert after["nodes"][0]["props"]["data-nav-warn"] == "broken"


# ---------- idempotency ---------------------------------------------------

class TestIdempotency:
    def test_second_run_repairs_nothing(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "pages": [{"route": "/favourites"}],
        }, schemas={"favourites": {
            "nodes": [{"type": "Button", "props": {"navigate": "/favourites/details/abc"}}]
        }})
        r1 = apply_navigate_target_guard(str(tmp_path))
        r2 = apply_navigate_target_guard(str(tmp_path))
        assert len(r1["repaired"]) == 1
        assert r2["repaired"] == []
        assert r2["marked"] == []


# ---------- multi-key coverage --------------------------------------------

class TestMultipleNavKeys:
    def test_href_and_to_and_url_all_checked(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "pages": [{"route": "/orders"}],
        }, schemas={"orders": {
            "nodes": [
                {"type": "Link", "props": {"href": "/orders"}},         # ok
                {"type": "Link", "props": {"href": "/missing"}},        # marked
                {"type": "NavLink", "props": {"to": "/orders"}},        # ok
            ]
        }})
        r = apply_navigate_target_guard(str(tmp_path))
        marked_targets = [m["target"] for m in r["marked"]]
        assert marked_targets == ["/missing"]


# ---------- no-op cases ---------------------------------------------------

class TestNoOp:
    def test_no_schemas_dir(self, tmp_path: Path):
        r = apply_navigate_target_guard(str(tmp_path))
        assert r["files_scanned"] == 0

    def test_no_known_routes(self, tmp_path: Path):
        (tmp_path / "src" / "contracts").mkdir(parents=True)
        (tmp_path / "src" / "schemas").mkdir(parents=True)
        (tmp_path / "src" / "contracts" / "plan.json").write_text("{}")
        (tmp_path / "src" / "schemas" / "x.json").write_text(json.dumps({"nodes": [
            {"type": "Button", "props": {"navigate": "/anywhere"}},
        ]}))
        r = apply_navigate_target_guard(str(tmp_path))
        # No plan routes → we don't have enough information to decide, skip.
        assert r["repaired"] == []
        assert r["marked"] == []
