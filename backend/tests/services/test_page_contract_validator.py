"""Tests for services.page_contract_validator — pages vs component contracts.

The validator checks every emitted page schema against the SAME contract
the renderer enforces at runtime (packages/registry/dist/
component-contracts.json + the renderer's built-in node set), so a page
that would render a "⚠ Unknown component" placeholder or a bare
data-less Table fails at generation time instead of in front of the user.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.page_contract_validator import validate_pages

# A miniature contract map in the real file's shape.
_CONTRACTS = {
    "Table": {
        "columns": {"type": "array"},
        "rows": {"type": "any", "optional": True},
        "data": {"type": "any", "optional": True},
        "dataSource": {"type": "string", "optional": True},
    },
    "Select": {
        "options": {"type": "array", "optional": True},
        "optionsFrom": {"type": "object", "optional": True},
        "name": {"type": "string", "optional": True},
    },
    "Hero": {
        "headline": {"type": "string"},
        "layout": {"type": "enum", "enum": ["left", "center"]},
    },
    "CustomBlock": {"html": {"type": "string", "optional": True}},
    "Button": {"label": {"type": "string", "optional": True}},
}


def _mk_app(tmp_path: Path, pages: dict[str, dict]) -> Path:
    root = tmp_path / "app"
    sdir = root / "src" / "schemas"
    sdir.mkdir(parents=True)
    for fname, root_node in pages.items():
        (sdir / fname).write_text(json.dumps(
            {"id": fname, "route": "/" + fname[:-5], "root": root_node}))
    return root


def _issues(report: dict, code: str) -> list[dict]:
    return [i for i in report["issues"] if i["code"] == code]


@pytest.fixture()
def contracts():
    return _CONTRACTS


def test_unknown_component_type_flagged(tmp_path, contracts):
    root = _mk_app(tmp_path, {"a.json": {
        "type": "Stack", "children": [{"type": "FancyWidget", "props": {}}]}})
    rep = validate_pages(root, contracts=contracts)
    hits = _issues(rep, "unknown_type")
    assert len(hits) == 1
    assert hits[0]["component"] == "FancyWidget"
    assert hits[0]["page"] == "a.json"


def test_renderer_builtins_not_flagged(tmp_path, contracts):
    kids = [{"type": t, "props": {}} for t in
            ("Box", "Text", "Repeat", "Conditional", "DataBoundary",
             "Icon", "Slot", "Custom")]
    root = _mk_app(tmp_path, {"a.json": {"type": "Stack", "children": kids}})
    rep = validate_pages(root, contracts=contracts)
    assert _issues(rep, "unknown_type") == []


def test_missing_required_prop_flagged(tmp_path, contracts):
    root = _mk_app(tmp_path, {"a.json": {
        "type": "Hero", "props": {"headline": "Hi"}}})
    rep = validate_pages(root, contracts=contracts)
    hits = _issues(rep, "missing_required_prop")
    assert [h["prop"] for h in hits] == ["layout"]


def test_table_without_binding_flagged(tmp_path, contracts):
    root = _mk_app(tmp_path, {"a.json": {
        "type": "Table", "props": {"columns": []}}})
    rep = validate_pages(root, contracts=contracts)
    assert len(_issues(rep, "unbound_table")) == 1


def test_table_with_rows_binding_ok(tmp_path, contracts):
    root = _mk_app(tmp_path, {"a.json": {
        "type": "Table", "props": {"columns": [], "rows": "{{documents}}"}}})
    rep = validate_pages(root, contracts=contracts)
    assert _issues(rep, "unbound_table") == []


def test_bare_select_flagged(tmp_path, contracts):
    root = _mk_app(tmp_path, {"a.json": {
        "type": "Select", "props": {"name": "status", "options": []}}})
    rep = validate_pages(root, contracts=contracts)
    assert len(_issues(rep, "bare_select")) == 1


def test_select_with_options_from_ok(tmp_path, contracts):
    root = _mk_app(tmp_path, {"a.json": {
        "type": "Select",
        "props": {"name": "ownerId",
                  "optionsFrom": {"dataSource": "users"}}}})
    rep = validate_pages(root, contracts=contracts)
    assert _issues(rep, "bare_select") == []


def test_bound_iframe_customblock_flagged(tmp_path, contracts):
    root = _mk_app(tmp_path, {"a.json": {
        "type": "CustomBlock",
        "props": {"html": '<iframe src="{{selected.filePath}}"></iframe>'}}})
    rep = validate_pages(root, contracts=contracts)
    assert len(_issues(rep, "bound_iframe")) == 1


def test_clean_page_passes(tmp_path, contracts):
    root = _mk_app(tmp_path, {"a.json": {
        "type": "Stack", "children": [
            {"type": "Hero", "props": {"headline": "Hi", "layout": "left"}},
            {"type": "Table",
             "props": {"columns": [], "dataSource": "documents"}},
            {"type": "Button", "props": {"label": "Go"}},
        ]}})
    rep = validate_pages(root, contracts=contracts)
    assert rep["issues"] == []
    assert rep["summary"]["pages"] == 1
    assert rep["summary"]["errors"] == 0


def test_missing_schemas_dir_no_crash(tmp_path, contracts):
    rep = validate_pages(tmp_path / "nope", contracts=contracts)
    assert rep["issues"] == []
    assert rep["summary"]["pages"] == 0


def test_validate_schema_dict_single_doc(contracts):
    from services.page_contract_validator import validate_schema_dict
    doc = {"id": "x", "root": {"type": "Stack", "children": [
        {"type": "FancyWidget", "props": {}},
        {"type": "Hero", "props": {"headline": "Hi"}},
    ]}}
    issues = validate_schema_dict(doc, "x", contracts)
    assert {i["code"] for i in issues} == {"unknown_type",
                                          "missing_required_prop"}
    assert validate_schema_dict(None, "x", contracts) == []


def test_format_issues_for_revise(contracts):
    from services.page_contract_validator import (
        format_issues_for_revise, validate_schema_dict,
    )
    doc = {"root": {"type": "Hero", "id": "h1",
                    "props": {"headline": "Hi"}}}
    text = format_issues_for_revise(validate_schema_dict(doc, "x", contracts))
    assert "missing_required_prop" in text
    assert "Hero" in text and "layout" in text


def test_real_contracts_load(tmp_path):
    """Default contracts path loads the registry dist when present."""
    root = _mk_app(tmp_path, {"a.json": {"type": "Stack", "children": []}})
    rep = validate_pages(root)  # no contracts kwarg
    # Either the dist file exists (validation ran) or it doesn't
    # (validator degrades to skipped) — both must be crash-free.
    assert "summary" in rep
