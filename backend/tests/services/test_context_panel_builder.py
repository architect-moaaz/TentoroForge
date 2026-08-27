"""Tests for services.context_panel_builder — Spec B4 context side-rail.

Deterministic post-generate pass that wraps single-primary-FK create/edit
forms in a Split[2:1] layout with a Card+DescriptionList context panel on
the right. Idempotent, flag-gated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.context_panel_builder import inject_context_panels


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch):
    """The pass is off by default (spec rollout gate). Turn it on for tests."""
    monkeypatch.setenv("FORGE_FORM_CONTEXT_PANEL", "1")


def _write(tmp: Path, rel: str, obj: dict) -> Path:
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _registry_with_lease() -> dict:
    return {
        "entities": {
            "Lease": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "unitNumber": {"type": "varchar"},
                "monthlyRent": {"type": "numeric"},
                "startDate": {"type": "date"},
                "ownerId": {"type": "uuid"},   # excluded — system
                "createdAt": {"type": "timestamp"},  # excluded — lifecycle
            }},
            "RentPayment": {"fields": {
                "id": {"type": "uuid", "primaryKey": True},
                "leaseId": {"type": "uuid"},
                "amount": {"type": "numeric"},
            }},
        },
    }


def _form_page_with_lease_fk() -> dict:
    return {
        "route": "/payments/new",
        "root": {"type": "Form", "props": {"workflow": "CreatePayment"}, "children": [
            {"type": "Stack", "children": [
                {"type": "Select", "props": {
                    "name": "leaseId", "label": "Lease",
                    "optionsFrom": {"source": "Lease", "value": "id", "label": "unitNumber"},
                }},
                {"type": "NumberInput", "props": {"name": "amount", "label": "Amount"}},
            ]},
        ]},
    }


# ────────────────────────────────────────────────────────────
# Flag gate
# ────────────────────────────────────────────────────────────

class TestFlagGate:
    def test_no_op_when_flag_off(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FORM_CONTEXT_PANEL", "0")
        _write(tmp_path, "registry.json", _registry_with_lease())
        _write(tmp_path, "src/schemas/payments/new.json", _form_page_with_lease_fk())
        res = inject_context_panels(str(tmp_path))
        assert res == {"wrapped": 0, "files": 0}

    def test_missing_dir_safe(self, tmp_path):
        assert inject_context_panels(str(tmp_path)) == {"wrapped": 0, "files": 0}


# ────────────────────────────────────────────────────────────
# Wrapping — single primary FK
# ────────────────────────────────────────────────────────────

class TestWrap:
    def test_wraps_single_fk_form_in_split(self, tmp_path):
        _write(tmp_path, "registry.json", _registry_with_lease())
        page_path = _write(tmp_path, "src/schemas/payments/new.json", _form_page_with_lease_fk())
        res = inject_context_panels(str(tmp_path))
        assert res == {"wrapped": 1, "files": 1}
        after = json.loads(page_path.read_text())
        assert after["root"]["type"] == "Split"
        assert after["root"]["props"]["ratio"] == "2:1"
        # Original form preserved as the LEFT child; Card as the RIGHT.
        assert after["root"]["children"][0]["type"] == "Form"
        assert after["root"]["children"][1]["type"] == "Card"

    def test_panel_shows_target_entity_key_fields(self, tmp_path):
        _write(tmp_path, "registry.json", _registry_with_lease())
        page_path = _write(tmp_path, "src/schemas/payments/new.json", _form_page_with_lease_fk())
        inject_context_panels(str(tmp_path))
        after = json.loads(page_path.read_text())
        card = after["root"]["children"][1]
        assert card["type"] == "Card"
        dlist = next(c for c in card["children"] if c["type"] == "DescriptionList")
        labels = [it["label"] for it in dlist["props"]["items"]]
        # unitNumber wins the label slot; monthlyRent, startDate come next.
        # ownerId + createdAt are excluded (system/lifecycle).
        assert "Unit Number" in labels
        assert "Monthly Rent" in labels
        assert "Start Date" in labels
        assert "Owner Id" not in labels
        assert "Created At" not in labels

    def test_panel_binds_items_to_form_scope(self, tmp_path):
        """Values reference {{form.<col>}} so B5's onChange-fetch runtime
        can populate them when it fires — until then, the FK's own value
        at least renders."""
        _write(tmp_path, "registry.json", _registry_with_lease())
        page_path = _write(tmp_path, "src/schemas/payments/new.json", _form_page_with_lease_fk())
        inject_context_panels(str(tmp_path))
        after = json.loads(page_path.read_text())
        dlist = after["root"]["children"][1]["children"][1]
        values = [it["value"] for it in dlist["props"]["items"]]
        assert all(v.startswith("{{form.") and v.endswith("}}") for v in values)


# ────────────────────────────────────────────────────────────
# Skip conditions
# ────────────────────────────────────────────────────────────

class TestSkip:
    def test_skips_form_with_no_fk(self, tmp_path):
        _write(tmp_path, "registry.json", _registry_with_lease())
        page = {
            "route": "/notes/new",
            "root": {"type": "Form", "props": {"workflow": "CreateNote"}, "children": [
                {"type": "Input", "props": {"name": "text", "label": "Note"}},
            ]},
        }
        _write(tmp_path, "src/schemas/notes/new.json", page)
        assert inject_context_panels(str(tmp_path))["wrapped"] == 0

    def test_skips_form_with_multiple_fks_unless_primary_flagged(self, tmp_path):
        _write(tmp_path, "registry.json", _registry_with_lease())
        page = {
            "route": "/x/new",
            "root": {"type": "Form", "props": {"workflow": "X"}, "children": [
                {"type": "Select", "props": {"name": "leaseId",
                    "optionsFrom": {"source": "Lease", "value": "id", "label": "unitNumber"}}},
                {"type": "Select", "props": {"name": "tenantId",
                    "optionsFrom": {"source": "User", "value": "id", "label": "email"}}},
            ]},
        }
        _write(tmp_path, "src/schemas/x/new.json", page)
        assert inject_context_panels(str(tmp_path))["wrapped"] == 0

    def test_uses_primary_flag_when_multiple_fks_and_one_marked(self, tmp_path):
        _write(tmp_path, "registry.json", _registry_with_lease())
        page = {
            "route": "/x/new",
            "root": {"type": "Form", "props": {"workflow": "X"}, "children": [
                {"type": "Select", "props": {"name": "leaseId", "_primary": True,
                    "optionsFrom": {"source": "Lease", "value": "id", "label": "unitNumber"}}},
                {"type": "Select", "props": {"name": "tenantId",
                    "optionsFrom": {"source": "User", "value": "id", "label": "email"}}},
            ]},
        }
        page_path = _write(tmp_path, "src/schemas/x/new.json", page)
        res = inject_context_panels(str(tmp_path))
        assert res["wrapped"] == 1
        after = json.loads(page_path.read_text())
        # The panel targets Lease (the flagged one), not User.
        card = after["root"]["children"][1]
        assert "Lease" in card["children"][0]["props"]["text"]

    def test_skips_non_form_pages(self, tmp_path):
        _write(tmp_path, "registry.json", _registry_with_lease())
        page = {
            "route": "/payments",  # list page, no /new or /edit
            "root": {"type": "Form", "children": []},
        }
        _write(tmp_path, "src/schemas/payments/index.json", page)
        assert inject_context_panels(str(tmp_path))["wrapped"] == 0


# ────────────────────────────────────────────────────────────
# Idempotency
# ────────────────────────────────────────────────────────────

class TestIdempotent:
    def test_second_run_no_op(self, tmp_path):
        _write(tmp_path, "registry.json", _registry_with_lease())
        _write(tmp_path, "src/schemas/payments/new.json", _form_page_with_lease_fk())
        assert inject_context_panels(str(tmp_path))["wrapped"] == 1
        assert inject_context_panels(str(tmp_path))["wrapped"] == 0
