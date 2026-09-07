"""Tests for services.text_template_backstop (B-021.2 root fix wiring).

The backstop runs on every generation. It should:
  * Fix the exact B-021.2 case (LLM-authored "No plant batchs yet." → "No plant batches yet.")
  * Fix EmptyState components that start "No … yet."
  * Replace fuzzy standard-button labels (Add, New, Save) with the deterministic
    equivalent.
  * Leave domain-specific strings (helperText, description, custom labels) alone.
  * Be idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.text_template_backstop import apply_text_template_backstop


def _make_app(root: Path, *,
              plan: dict | None = None,
              schemas: dict[str, dict] | None = None) -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    if plan is not None:
        (root / "src" / "contracts" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    for name, doc in (schemas or {}).items():
        (root / "src" / "schemas" / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "src" / "schemas" / f"{name}.json").read_text(encoding="utf-8"))


# ---------- empty state replacement ---------------------------------------

class TestEmptyStateReplacement:

    def test_b021_2_exact_case(self, tmp_path: Path):
        """The LLM authored 'No plant batchs yet.' — backstop must fix it."""
        _make_app(tmp_path, plan={
            "entities": {"PlantBatch": {"fields": []}},
            "pages": [{"route": "/batches", "entity": "PlantBatch"}],
        }, schemas={"batches": {
            "route": "/batches",
            "nodes": [{
                "type": "Table",
                "props": {
                    "dataSource": "batches",
                    "emptyStateText": "No plant batchs yet.",
                },
            }],
        }})
        r = apply_text_template_backstop(str(tmp_path))
        assert r["files_scanned"] == 1
        after = _read(tmp_path, "batches")
        assert after["nodes"][0]["props"]["emptyStateText"] == "No plant batches yet."

    def test_fixes_boy_style_zero_change(self, tmp_path: Path):
        """"Boys" is correct — no reason to touch it. Ensure the fix runs
        idempotently without corrupting correct plurals."""
        _make_app(tmp_path, plan={
            "entities": {"Boy": {"fields": []}},
            "pages": [{"route": "/boys", "entity": "Boy"}],
        }, schemas={"boys": {
            "route": "/boys",
            "nodes": [{"type": "Table", "props": {
                "dataSource": "boys",
                "emptyStateText": "No boys yet.",
            }}],
        }})
        apply_text_template_backstop(str(tmp_path))
        after = _read(tmp_path, "boys")
        assert after["nodes"][0]["props"]["emptyStateText"] == "No boys yet."

    def test_replaces_emptystate_component(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"City": {"fields": []}},
            "pages": [{"route": "/cities", "entity": "City"}],
        }, schemas={"cities": {
            "route": "/cities",
            "nodes": [{
                "type": "EmptyState",
                "props": {"title": "No citys yet.", "message": "Please add one"},
            }],
        }})
        apply_text_template_backstop(str(tmp_path))
        after = _read(tmp_path, "cities")
        assert after["nodes"][0]["props"]["title"] == "No cities yet."
        # message doesn't look like empty-state pattern → untouched
        assert after["nodes"][0]["props"]["message"] == "Please add one"

    def test_leaves_custom_messages_alone(self, tmp_path: Path):
        """Domain-specific empty-state strings must pass through."""
        _make_app(tmp_path, plan={
            "entities": {"Task": {"fields": []}},
            "pages": [{"route": "/tasks", "entity": "Task"}],
        }, schemas={"tasks": {
            "route": "/tasks",
            "nodes": [{
                "type": "EmptyState",
                "props": {
                    "title": "You're all caught up",
                    "message": "Take a break — nothing needs your attention.",
                },
            }],
        }})
        apply_text_template_backstop(str(tmp_path))
        after = _read(tmp_path, "tasks")
        assert after["nodes"][0]["props"]["title"] == "You're all caught up"


# ---------- button replacement --------------------------------------------

class TestButtonReplacement:
    def test_add_becomes_create_entity(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Plant": {"fields": []}},
            "pages": [{"route": "/plants", "entity": "Plant"}],
        }, schemas={"plants": {
            "route": "/plants",
            "nodes": [{"type": "Button", "props": {"text": "Add"}}],
        }})
        apply_text_template_backstop(str(tmp_path))
        after = _read(tmp_path, "plants")
        assert after["nodes"][0]["props"]["text"] == "Create Plant"

    def test_save_becomes_save_changes(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Plant": {"fields": []}},
            "pages": [{"route": "/plants", "entity": "Plant"}],
        }, schemas={"plants": {
            "route": "/plants",
            "nodes": [{"type": "Button", "props": {"text": "Save"}}],
        }})
        apply_text_template_backstop(str(tmp_path))
        after = _read(tmp_path, "plants")
        assert after["nodes"][0]["props"]["text"] == "Save changes"

    def test_custom_domain_label_untouched(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"Delivery": {"fields": []}},
            "pages": [{"route": "/deliveries", "entity": "Delivery"}],
        }, schemas={"deliveries": {
            "route": "/deliveries",
            "nodes": [{"type": "Button", "props": {"text": "Confirm Pickup"}}],
        }})
        apply_text_template_backstop(str(tmp_path))
        after = _read(tmp_path, "deliveries")
        assert after["nodes"][0]["props"]["text"] == "Confirm Pickup"


# ---------- idempotency ---------------------------------------------------

class TestIdempotency:
    def test_running_twice_is_stable(self, tmp_path: Path):
        _make_app(tmp_path, plan={
            "entities": {"PlantBatch": {"fields": []}},
            "pages": [{"route": "/batches", "entity": "PlantBatch"}],
        }, schemas={"batches": {
            "route": "/batches",
            "nodes": [{"type": "Table", "props": {
                "dataSource": "batches", "emptyStateText": "No plant batchs yet.",
            }}],
        }})
        apply_text_template_backstop(str(tmp_path))
        first = _read(tmp_path, "batches")
        apply_text_template_backstop(str(tmp_path))
        second = _read(tmp_path, "batches")
        assert first == second
        assert first["nodes"][0]["props"]["emptyStateText"] == "No plant batches yet."


# ---------- no-op cases ---------------------------------------------------

class TestNoOp:
    def test_missing_schemas_dir(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        r = apply_text_template_backstop(str(tmp_path))
        assert r["files_scanned"] == 0

    def test_page_with_no_entity_still_scans(self, tmp_path: Path):
        """No plan, no entity — the pass shouldn't crash."""
        (tmp_path / "src" / "schemas").mkdir(parents=True)
        (tmp_path / "src" / "schemas" / "home.json").write_text(json.dumps({
            "route": "/",
            "nodes": [{"type": "Heading", "props": {"text": "Welcome"}}],
        }), encoding="utf-8")
        r = apply_text_template_backstop(str(tmp_path))
        assert r["files_scanned"] == 1
