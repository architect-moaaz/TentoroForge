"""wizard_page_pass — Spec E Wave 3.

Deterministic post-gen pass that collapses `page.wizard`-declared
pages into a single library Wizard component in the emitted schema.
Flag-gated on FORGE_E_PATTERNS.
"""
from __future__ import annotations

import json
import os

import pytest

from services.wizard_page_pass import is_enabled, run


def _write_page(root, name, schema):
    d = root / "src" / "schemas"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(schema), encoding="utf-8")


def _write_workflow(root, name):
    d = root / "src" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps({"name": name}), encoding="utf-8")


# ── enablement ─────────────────────────────────────────────────

def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_E_PATTERNS", raising=False)
    assert is_enabled() is False
    assert run(str(tmp_path)) == {"enabled": False, "pages_touched": []}


def test_enabled_when_flag_truthy(monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    assert is_enabled() is True


# ── no-op paths ────────────────────────────────────────────────

def test_no_pages_with_wizard_declaration(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "plain", {"root": {"type": "Card"}})
    report = run(str(tmp_path))
    assert report["pages_touched"] == []


def test_missing_schemas_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    report = run(str(tmp_path))
    assert report["pages_touched"] == []


# ── happy paths ────────────────────────────────────────────────

def test_injects_wizard_when_page_declares_it(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "apply", {
        "route": "/apply",
        "entity": "Candidate",
        "wizard": {
            "steps": [
                {"id": "personal", "title": "Personal",
                 "fields": ["full_name", "email"]},
                {"id": "docs", "title": "Documents",
                 "fields": ["cv"]},
            ],
        },
        "actions": [{"kind": "form_submit", "workflow": "createApplication"}],
        "root": {"type": "Stack", "children": []},
    })
    report = run(str(tmp_path))
    assert len(report["pages_touched"]) == 1
    schema = json.loads((tmp_path / "src" / "schemas" / "apply.json").read_text(encoding="utf-8"))
    # Wizard is now in the root children.
    root = schema["root"]
    types = [c.get("type") for c in root.get("children", [])]
    assert "Wizard" in types
    wiz = next(c for c in root["children"] if c["type"] == "Wizard")
    steps = wiz["props"]["steps"]
    assert len(steps) == 2
    assert steps[0]["fields"][0]["name"] == "full_name"
    assert wiz["props"]["onComplete"] == "createApplication"
    assert schema["_wave3"]["wizard_applied"] is True


def test_idempotent_when_wizard_already_present(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "apply", {
        "wizard": {"steps": [{"id": "s", "title": "S", "fields": ["x"]}]},
        "root": {"type": "Wizard", "props": {"steps": []}},
    })
    report = run(str(tmp_path))
    assert report["pages_touched"] == []


def test_reuses_existing_field_kinds(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "apply", {
        "wizard": {"steps": [{"id": "s", "title": "S",
                              "fields": ["notes", "role"]}]},
        "root": {
            "type": "Form",
            "props": {
                "fields": [
                    {"name": "notes", "kind": "textarea", "label": "Notes"},
                    {"name": "role", "kind": "select", "label": "Role",
                     "options": [{"value": "a", "label": "A"}]},
                ],
            },
        },
    })
    run(str(tmp_path))
    schema = json.loads((tmp_path / "src" / "schemas" / "apply.json").read_text(encoding="utf-8"))
    # When the root is a Form (no children), the wizard replaces it entirely.
    root = schema["root"]
    wiz = root if root.get("type") == "Wizard" else next(
        c for c in root.get("children", []) if c["type"] == "Wizard"
    )
    kinds = {f["name"]: f["kind"] for f in wiz["props"]["steps"][0]["fields"]}
    assert kinds == {"notes": "textarea", "role": "select"}


def test_infers_workflow_from_entity_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_workflow(tmp_path, "createCandidate")
    _write_page(tmp_path, "new", {
        "entity": "Candidate",
        "wizard": {"steps": [{"id": "s", "title": "S", "fields": ["name"]}]},
        "root": {"type": "Stack", "children": []},
    })
    run(str(tmp_path))
    schema = json.loads((tmp_path / "src" / "schemas" / "new.json").read_text(encoding="utf-8"))
    wiz = next(c for c in schema["root"]["children"] if c["type"] == "Wizard")
    assert wiz["props"].get("onComplete") == "createCandidate"


def test_wizard_step_declaring_nextif_is_carried_through(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_page(tmp_path, "apply", {
        "wizard": {"steps": [
            {"id": "confirm", "title": "Confirm",
             "fields": ["accept"], "nextIf": "accept"},
        ]},
        "root": {"type": "Stack", "children": []},
    })
    run(str(tmp_path))
    schema = json.loads((tmp_path / "src" / "schemas" / "apply.json").read_text(encoding="utf-8"))
    wiz = next(c for c in schema["root"]["children"] if c["type"] == "Wizard")
    assert wiz["props"]["steps"][0]["nextIf"] == "accept"
