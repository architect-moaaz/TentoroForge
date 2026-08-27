"""SV-STRICT-4 — the ``why`` slot is filled from the Promises set.

Promises come from :mod:`services.blueprint_promises` — persona jobs
(product-brief), page purposes (plan / nav-flow), workflow purposes
(plan). When ``extract_component_contracts(output_dir)`` runs on a
tree that includes those sources, every affected contract's
``slots["why"]`` becomes non-empty + ``verifiable=True`` +
``source="blueprint"``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.component_contract import extract_component_contracts


def _write(root: Path, rel: str, data: dict | list) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def app_with_promises(tmp_path: Path) -> Path:
    _write(tmp_path, "src/contracts/nav-flow.json", {
        "version": "1.0", "initialPage": "schedule",
        "pages": [
            {"id": "schedule", "route": "/schedule", "title": "Schedule",
             "schemaFile": "src/schemas/schedule.json",
             "layout": None, "params": [], "shell": True},
        ],
        "transitions": [], "guards": {}, "auth_routes": [],
        "authGated": True,
    })
    _write(tmp_path, "src/contracts/plan.json", {
        "pages": [{
            "route": "/schedule", "name": "Schedule",
            "description": "Where students book classes",
        }],
        "workflows": [{
            "name": "BookClass",
            "description": "Reserves a spot in a session",
            "inputs": [], "trigger": {"kind": "form"},
        }],
        "actors": [],
    })
    _write(tmp_path, "src/contracts/product-brief.json", {
        "personas": [{
            "id": "member", "name": "Member", "role": "member",
            "jobs": [{"id": "book", "label": "Book a class",
                      "primary_entities": ["Session"]}],
        }],
    })
    _write(tmp_path, "registry.json", {
        "entities": {"Session": {"fields": {"id": {"type": "uuid"}}}},
        "relations": [], "api_routes": {}, "components": {}, "pages": {},
        "workflow_bindings": {}, "rules": {},
    })
    _write(tmp_path, "src/schemas/schedule.json", {
        "id": "schedule", "route": "/schedule", "dataSources": [],
        "root": {"type": "Section", "props": {}, "children": []},
    })
    return tmp_path


# ── Fill semantics ───────────────────────────────────────────────────────


class TestPageWhy:
    def test_page_why_names_purpose(self, app_with_promises: Path):
        page = next(c for c in extract_component_contracts(app_with_promises)
                    if c.component_type == "page")
        why = page.slots["why"]
        assert "book classes" in why.value.lower() \
            or "book" in why.value.lower()
        assert why.verifiable is True
        assert why.source == "blueprint"


class TestWorkflowWhy:
    def test_workflow_why_names_purpose(self, app_with_promises: Path):
        wf = next(c for c in extract_component_contracts(app_with_promises)
                  if c.component_type == "workflow")
        why = wf.slots["why"]
        assert "spot" in why.value.lower() or "session" in why.value.lower()
        assert why.verifiable is True
        assert why.source == "blueprint"


class TestEntityWhy:
    def test_entity_why_mentions_persona_job(self, app_with_promises: Path):
        # Session is the primary_entities target of a persona job, so its
        # ComponentContract.why should surface that persona-job link.
        ent = next(c for c in extract_component_contracts(app_with_promises)
                   if c.component_type == "entity")
        why = ent.slots["why"]
        assert "Book a class" in why.value or "book" in why.value.lower()
        assert why.source == "blueprint"


# ── Absence ──────────────────────────────────────────────────────────────


class TestNoPromises:
    def test_no_promises_leaves_why_empty(self, tmp_path: Path):
        # Same skeleton as the fixture MINUS product-brief and MINUS
        # plan page description — no promise data anywhere.
        _write(tmp_path, "src/contracts/nav-flow.json", {
            "version": "1.0", "initialPage": "home",
            "pages": [{"id": "home", "route": "/", "title": "home",
                        "schemaFile": "src/schemas/home.json",
                        "layout": None, "params": [], "shell": True}],
            "transitions": [], "guards": {}, "auth_routes": [], "authGated": False,
        })
        _write(tmp_path, "src/schemas/home.json", {
            "id": "home", "route": "/", "dataSources": [],
            "root": {"type": "Section", "props": {}, "children": []},
        })
        _write(tmp_path, "registry.json", {
            "entities": {}, "relations": [], "api_routes": {},
            "components": {}, "pages": {}, "workflow_bindings": {}, "rules": {},
        })
        contracts = extract_component_contracts(tmp_path)
        # nav-flow.title alone counts as a page purpose — that's fine.
        # The important invariant: no CRASH and any component without a
        # promise source stays with empty why.
        for c in contracts:
            if c.component_type in ("entity", "workflow"):
                # No promise for these types when there are no personas
                # and no workflows.
                assert c.slots["why"].value == ""
                assert c.slots["why"].verifiable is False
