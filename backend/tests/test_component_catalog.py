"""Component catalog — reads the library's starter.json so Smith
knows what components exist. Falls back gracefully when the file is
missing (dev / test envs where the library hasn't built)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import component_catalog as cc


@pytest.fixture(autouse=True)
def _reset_cache():
    cc.invalidate_cache()
    yield
    cc.invalidate_cache()


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def test_reads_starter_json_when_present(tmp_path, monkeypatch):
    p = tmp_path / "starter.json"
    p.write_text(json.dumps({
        "Button": {"props": {"label": {}, "onClick": {}, "intent": {}}},
        "Table":  {"props": {"columns": {}, "dataSource": {}}},
    }), encoding="utf-8")
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_PATH", str(p))

    assert cc.component_names() == ["Button", "Table"]
    assert cc.has_component("Button")
    assert cc.has_component("Kanban") is False
    assert cc.props_for("Button") == ["intent", "label", "onClick"]
    assert cc.props_for("Nonexistent") == []


def test_missing_starter_returns_empty(tmp_path, monkeypatch):
    """A dev env where the library hasn't built shouldn't crash Smith
    — the catalog is empty and callers should degrade."""
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_PATH", str(tmp_path / "nope.json"))
    assert cc.component_names() == []
    assert cc.has_component("Button") is False


def test_malformed_starter_returns_empty(tmp_path, monkeypatch):
    p = tmp_path / "starter.json"
    p.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_PATH", str(p))
    assert cc.list_components() == {}


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #

def test_caches_by_default(tmp_path, monkeypatch):
    p = tmp_path / "starter.json"
    p.write_text(json.dumps({"Button": {"props": {"label": {}}}}), encoding="utf-8")
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_PATH", str(p))

    assert cc.component_names() == ["Button"]
    # Overwrite the file — cached result should NOT reflect it.
    p.write_text(json.dumps({"Button": {}, "Table": {}}), encoding="utf-8")
    assert cc.component_names() == ["Button"]
    cc.invalidate_cache()
    assert cc.component_names() == ["Button", "Table"]


def test_cache_disabled_env_forces_refresh(tmp_path, monkeypatch):
    p = tmp_path / "starter.json"
    p.write_text(json.dumps({"Button": {}}), encoding="utf-8")
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_PATH", str(p))
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_CACHE", "0")

    assert cc.component_names() == ["Button"]
    p.write_text(json.dumps({"Button": {}, "Table": {}}), encoding="utf-8")
    assert cc.component_names() == ["Button", "Table"]


# --------------------------------------------------------------------------- #
# Prompt formatting
# --------------------------------------------------------------------------- #

def test_format_component_context_lists_names_and_props(tmp_path, monkeypatch):
    p = tmp_path / "starter.json"
    p.write_text(json.dumps({
        "Button": {"props": {"label": {}, "onClick": {}, "intent": {}}},
        "Table":  {"props": {"columns": {}, "dataSource": {}}},
    }), encoding="utf-8")
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_PATH", str(p))

    out = cc.format_component_context()
    assert "Button(intent, label, onClick)" in out
    assert "Table(columns, dataSource)" in out
    assert "2 total" in out


def test_format_component_context_falls_back_to_names_only_over_budget(
    tmp_path, monkeypatch,
):
    p = tmp_path / "starter.json"
    p.write_text(json.dumps({
        f"Comp{i}": {"props": {f"prop{j}": {} for j in range(20)}}
        for i in range(200)
    }), encoding="utf-8")
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_PATH", str(p))

    out = cc.format_component_context(budget_chars=500)
    # Every name appears, but no per-prop breakdown
    assert "Comp0" in out
    assert "Comp199" in out
    assert "prop0" not in out


def test_format_component_context_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_COMPONENT_CATALOG_PATH", str(tmp_path / "missing"))
    out = cc.format_component_context()
    assert "unavailable" in out.lower()
