"""filter_builder_pass — Spec E Wave 3.

Injects a FilterBuilder above the primary Table in every page schema
that declares ``page.list.filter_fields``. Flag-gated on
FORGE_E_PATTERNS. Idempotent + additive.
"""
from __future__ import annotations

import json

import pytest

from services.filter_builder_pass import is_enabled, run


def _write_page(root, name, schema):
    d = root / "src" / "schemas"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(schema), encoding="utf-8")


# ── enablement ─────────────────────────────────────────────────

def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_E_PATTERNS", raising=False)
    assert is_enabled() is False
    report = run(str(tmp_path))
    assert report == {"enabled": False, "pages_touched": []}


def test_enabled_when_flag_truthy(monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "on")
    assert is_enabled() is True


# ── no-op paths ────────────────────────────────────────────────

def test_no_filter_fields_declaration(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "plain", {"root": {"type": "Table"}})
    assert run(str(tmp_path))["pages_touched"] == []


def test_idempotent_when_filter_builder_already_present(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "orders", {
        "list": {"filter_fields": [{"name": "status", "type": "enum"}]},
        "root": {"type": "Stack", "children": [
            {"type": "FilterBuilder", "props": {"fields": []}},
            {"type": "Table", "props": {}},
        ]},
    })
    assert run(str(tmp_path))["pages_touched"] == []


def test_no_op_when_filter_bar_already_present(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "orders", {
        "list": {"filter_fields": [{"name": "status", "type": "enum"}]},
        "root": {"type": "Stack", "children": [
            {"type": "FilterBar", "props": {}},
            {"type": "Table", "props": {}},
        ]},
    })
    assert run(str(tmp_path))["pages_touched"] == []


# ── happy paths ────────────────────────────────────────────────

def test_injects_filter_builder_above_table(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "orders", {
        "list": {"filter_fields": [
            {"name": "status", "type": "enum",
             "operators": ["eq", "neq"]},
            {"name": "amount", "type": "number"},
        ]},
        "dataSources": [{"op": "list", "entity": "Order"}],
        "root": {"type": "Stack", "children": [
            {"type": "Heading", "props": {"text": "Orders"}},
            {"type": "Table", "props": {}},
        ]},
    })
    report = run(str(tmp_path))
    assert report["pages_touched"] == ["src/schemas/orders.json"]
    schema = json.loads((tmp_path / "src" / "schemas" / "orders.json").read_text(encoding="utf-8"))
    children = schema["root"]["children"]
    types = [c["type"] for c in children]
    # FilterBuilder is inserted immediately before the Table.
    assert types == ["Heading", "FilterBuilder", "Table"]
    fb = children[1]
    assert fb["props"]["paramKey"] == "filter"
    assert fb["props"]["fields"][0]["name"] == "status"
    # dataSource picked up the filter param hint.
    assert schema["dataSources"][0]["filter_query_param"] == "filter"
    assert schema["_wave3"]["filter_builder_applied"] is True


def test_injects_when_no_table_present(tmp_path, monkeypatch):
    """Falls back to prepending at the top of the root's children."""
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "orders", {
        "list": {"filter_fields": [{"name": "status", "type": "enum"}]},
        "root": {"type": "Stack", "children": [
            {"type": "Heading", "props": {"text": "Orders"}},
        ]},
    })
    run(str(tmp_path))
    schema = json.loads((tmp_path / "src" / "schemas" / "orders.json").read_text(encoding="utf-8"))
    types = [c["type"] for c in schema["root"]["children"]]
    assert types[0] == "FilterBuilder"


def test_works_with_top_level_components_list(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "orders", {
        "list": {"filter_fields": [{"name": "status", "type": "enum"}]},
        "components": [
            {"type": "Heading", "props": {"text": "H"}},
            {"type": "Table", "props": {}},
        ],
    })
    run(str(tmp_path))
    schema = json.loads((tmp_path / "src" / "schemas" / "orders.json").read_text(encoding="utf-8"))
    types = [c["type"] for c in schema["components"]]
    assert types == ["Heading", "FilterBuilder", "Table"]
