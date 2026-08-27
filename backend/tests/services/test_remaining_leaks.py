"""Tests for the last three fleet leaks: duplicate-route schema files,
anatomy scoring fairness, and workflow-entity page completeness."""
from __future__ import annotations

import json
from pathlib import Path


# ─────────── A: schema-file route dedup ───────────

def _mk_schemas(tmp_path: Path, files: dict[str, dict],
                registry: str | None = None) -> Path:
    root = tmp_path / "app"
    sdir = root / "src" / "schemas"
    for rel, doc in files.items():
        p = sdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc))
    if registry is not None:
        (sdir / "registry.ts").write_text(registry)
    return root


def test_registry_referenced_file_wins(tmp_path):
    from services.route_dedup import dedupe_schema_files
    root = _mk_schemas(tmp_path, {
        "index.json": {"id": "Index", "route": "/", "root": {"type": "Stack"}},
        "home.json": {"id": "Home", "route": "/", "root": {"type": "Stack"}},
    }, registry='export const routes = {\n  "/": () => import("./home.json"),\n};\n')
    rep = dedupe_schema_files(root)
    assert rep["removed"] == [{"route": "/", "removed": "index.json",
                               "kept": "home.json"}]
    assert not (root / "src" / "schemas" / "index.json").exists()
    assert (root / "src" / "schemas" / "home.json").exists()


def test_nested_path_wins_when_registry_silent(tmp_path):
    from services.route_dedup import dedupe_schema_files
    root = _mk_schemas(tmp_path, {
        "admin-analytics.json": {"id": "A", "route": "/admin/analytics",
                                 "root": {"type": "Stack"}},
        "admin/analytics.json": {"id": "B", "route": "/admin/analytics",
                                 "root": {"type": "Stack"}},
    })
    rep = dedupe_schema_files(root)
    assert rep["removed"][0]["removed"] == "admin-analytics.json"
    assert (root / "src" / "schemas" / "admin" / "analytics.json").exists()


def test_unique_routes_untouched_and_idempotent(tmp_path):
    from services.route_dedup import dedupe_schema_files
    root = _mk_schemas(tmp_path, {
        "a.json": {"id": "A", "route": "/a", "root": {"type": "Stack"}},
        "b.json": {"id": "B", "route": "/b", "root": {"type": "Stack"}},
    })
    assert dedupe_schema_files(root)["removed"] == []
    assert dedupe_schema_files(root)["removed"] == []


# ─────────── B: anatomy scoring fairness ───────────

def test_scorecard_anatomy_prefers_actionable_count(tmp_path):
    from services.scorecard import build_scorecard
    root = tmp_path / "app"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / "page-anatomy.json").write_text(json.dumps({
        "summary": {"injected": 6, "reported": 3, "reported_actionable": 1},
        "findings": [],
    }))
    card = build_scorecard(root)
    assert card["breakdown"]["anatomy"]["unfilled_slots"] == 1
    assert card["breakdown"]["anatomy"]["penalty"] == 3


def test_scorecard_anatomy_falls_back_to_reported(tmp_path):
    from services.scorecard import build_scorecard
    root = tmp_path / "app"
    (root / "contracts").mkdir(parents=True)
    (root / "contracts" / "page-anatomy.json").write_text(json.dumps({
        "summary": {"injected": 2, "reported": 2}}))
    card = build_scorecard(root)
    assert card["breakdown"]["anatomy"]["unfilled_slots"] == 2


# ─────────── C: workflow-entity page completeness ───────────

def test_plan_rule_flags_pageless_workflow_entity():
    from services.plan_validator import _rule_workflow_entity_has_page
    plan = {"pages": [{"name": "HomePage", "route": "/", "kind": "dashboard"}],
            "workflows": [{"name": "AdjustCreditsWorkflow",
                           "trigger": "manual", "steps": [
                               {"type": "action", "config": {
                                   "actionType": "db_update",
                                   "table": "credits"}}]}]}
    out = _rule_workflow_entity_has_page(plan)
    assert len(out) == 1
    assert out[0]["rule"] == "workflow_entity_has_page"
    assert out[0]["severity"] == "error"


def test_plan_rule_quiet_when_entity_page_exists():
    from services.plan_validator import _rule_workflow_entity_has_page
    plan = {"pages": [{"name": "CreditsPage", "route": "/credits",
                       "kind": "list"}],
            "workflows": [{"name": "AdjustCreditsWorkflow",
                           "trigger": "manual", "steps": [
                               {"type": "action", "config": {
                                   "actionType": "db_update",
                                   "table": "credits"}}]}]}
    assert _rule_workflow_entity_has_page(plan) == []


def test_materializer_falls_back_to_landing_page(tmp_path):
    from services.transition_materializer import materialize_workflow_launchers
    root = tmp_path / "app"
    (root / "workflows").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps({
        "pages": [{"name": "HomePage", "route": "/", "type": "dashboard"}],
        "workflows": [{"name": "AdjustCreditsWorkflow", "trigger": "manual",
                       "steps": []}],
    }))
    (root / "workflows" / "AdjustCreditsWorkflow.json").write_text(json.dumps(
        {"id": "AdjustCreditsWorkflow", "name": "AdjustCreditsWorkflow",
         "definition": {"nodes": []}}))
    (root / "src" / "schemas" / "index.json").write_text(json.dumps(
        {"id": "home", "route": "/",
         "root": {"type": "Stack", "children": []}}))
    rep = materialize_workflow_launchers(root)
    assert len(rep["injected"]) == 1, rep
    assert rep["injected"][0]["route"] == "/"
