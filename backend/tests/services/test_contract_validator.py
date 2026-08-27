"""Tests for services.contract_validator — Phase 3 page-side contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.contract_validator import (
    validate_output_dir,
    validate_page_schema,
)
from services.scope_card import Manifest, Page, persist_manifest


def _manifest_with(paths: list[str], workflows: list[str] | None = None) -> Manifest:
    return Manifest(
        pages=[Page(path=p, kind="custom") for p in paths],
        entities_with_tables=[],
        workflows=workflows or [],
    )


# ---------- route-not-in-manifest -----------------------------------------

def test_page_route_not_in_manifest_flagged():
    manifest = _manifest_with(["/scans", "/retailers"])
    schema = {"route": "/visitors", "root": {}}
    findings = validate_page_schema(schema, "visitors.json", manifest)
    assert any(f.code == "route-not-in-manifest" for f in findings)


def test_page_route_in_manifest_ok():
    manifest = _manifest_with(["/scans"])
    schema = {"route": "/scans", "root": {}}
    findings = validate_page_schema(schema, "scans.json", manifest)
    assert not any(f.code == "route-not-in-manifest" for f in findings)


# ---------- orphan-navigate ------------------------------------------------

def test_button_navigate_to_undeclared_route_flagged():
    manifest = _manifest_with(["/scans"])
    schema = {"route": "/scans", "root": {"type": "Stack", "children": [
        {"type": "Button", "props": {"navigate": "/settings"}},
    ]}}
    findings = validate_page_schema(schema, "scans.json", manifest)
    assert any(f.code == "orphan-navigate" for f in findings)


def test_button_navigate_to_dynamic_route_ok():
    """navigate="/scans/abc-uuid" should resolve to /scans/[id] in the manifest."""
    manifest = Manifest(
        pages=[Page(path="/scans/[id]", kind="detail")],
        entities_with_tables=[],
        workflows=[],
    )
    schema = {"route": "/scans/[id]", "root": {"type": "Button", "props": {
        "navigate": "/scans/a5373987-702a-4469-8d1e-aae1fe18f4e4",
    }}}
    findings = validate_page_schema(schema, "scans/[id].json", manifest)
    assert not any(f.code == "orphan-navigate" for f in findings)


# ---------- orphan-workflow ------------------------------------------------

def test_button_workflow_undeclared_warns():
    manifest = _manifest_with(["/scans"], workflows=["CreateScan"])
    schema = {"route": "/scans", "root": {"type": "Button", "props": {
        "workflow": "DeleteEverything",
    }}}
    findings = validate_page_schema(schema, "scans.json", manifest)
    assert any(f.code == "orphan-workflow" for f in findings)


def test_button_workflow_manifested_ok():
    manifest = _manifest_with(["/scans"], workflows=["CreateScan"])
    schema = {"route": "/scans", "root": {"type": "Button", "props": {
        "workflow": "CreateScan",
    }}}
    findings = validate_page_schema(schema, "scans.json", manifest)
    assert not any(f.code == "orphan-workflow" for f in findings)


def test_button_workflow_runtime_primitive_ok():
    """Login/Register/Logout/Checkout are runtime primitives, not in manifest."""
    manifest = _manifest_with(["/login"])
    schema = {"route": "/login", "root": {"type": "Button", "props": {
        "workflow": "Login",
    }}}
    findings = validate_page_schema(schema, "login.json", manifest)
    assert not any(f.code == "orphan-workflow" for f in findings)


# ---------- orphan-binding -------------------------------------------------

def test_binding_to_undeclared_datasource_warns():
    """`{{ghosts.field}}` when the only dataSource is `scan` is a warning."""
    manifest = _manifest_with(["/scans"])
    schema = {
        "route": "/scans",
        "dataSources": [{"name": "scan", "entity": "Scan"}],
        "root": {"type": "Text", "props": {"content": "{{ghosts.field}}"}},
    }
    findings = validate_page_schema(schema, "scans.json", manifest)
    assert any(f.code == "orphan-binding" for f in findings)


def test_binding_to_declared_datasource_ok():
    manifest = _manifest_with(["/scans"])
    schema = {
        "route": "/scans",
        "dataSources": [{"name": "scan", "entity": "Scan"}],
        "root": {"type": "Text", "props": {"content": "{{scan.status}}"}},
    }
    findings = validate_page_schema(schema, "scans.json", manifest)
    assert not any(f.code == "orphan-binding" for f in findings)


def test_binding_user_scope_ok():
    """`{{user.name}}` is always a well-known scope."""
    manifest = _manifest_with(["/scans"])
    schema = {
        "route": "/scans",
        "root": {"type": "Text", "props": {"content": "Welcome, {{user.name}}!"}},
    }
    findings = validate_page_schema(schema, "scans.json", manifest)
    assert not any(f.code == "orphan-binding" for f in findings)


def test_binding_repeat_item_scope_ok():
    """Repeat's `as` binding introduces the row scope; child refs resolve."""
    manifest = _manifest_with(["/history"])
    schema = {
        "route": "/history",
        "dataSources": [{"name": "scans", "entity": "Scan", "op": "list"}],
        "root": {
            "type": "Repeat", "bind": "scans", "as": "row",
            "children": [
                {"type": "Text", "props": {"content": "{{row.status}}"}},
            ],
        },
    }
    findings = validate_page_schema(schema, "history.json", manifest)
    # `row` should be treated as a scope because the Repeat sets `as="row"`.
    orphans = [f for f in findings if f.code == "orphan-binding"]
    # No orphan for `row.status` (Repeat's own children resolve `row`)
    assert not any("row" in f.message for f in orphans)


# ---------- validate_output_dir round trip --------------------------------

def test_validate_output_dir_uses_persisted_manifest(tmp_path: Path):
    manifest = Manifest(
        pages=[Page(path="/scans", kind="list")],
        entities_with_tables=["Scan"],
        workflows=[],
    )
    persist_manifest(manifest, tmp_path)
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "scans.json").write_text(json.dumps({
        "route": "/scans",
        "root": {"type": "Button", "props": {"navigate": "/does-not-exist"}},
    }))
    (schemas / "visitors.json").write_text(json.dumps({
        "route": "/visitors",  # not in manifest
        "root": {},
    }))
    findings = validate_output_dir(tmp_path)
    codes = {f.code for f in findings}
    assert "route-not-in-manifest" in codes  # from visitors.json
    assert "orphan-navigate" in codes  # from scans.json


def test_validate_output_dir_no_manifest_returns_empty(tmp_path: Path):
    """Soft-fail when the pipeline hasn't produced a manifest yet."""
    assert validate_output_dir(tmp_path) == []
