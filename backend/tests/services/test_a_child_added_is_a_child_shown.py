"""Kids Vaccination Booking (aszjcc2k), 2026-09-26/27.

A parent added a child, was told "Child added", and My Children still said
"add your first child". Around it, the chat: a verify of "critical journeys"
re-composed 25 of 27 pages, ended on "could not be rendered — open it and have
a look", and "rebuild" after a fix was answered with the card to press when
the fix was already in the app.
"""
from __future__ import annotations

import importlib
import json
import time
from pathlib import Path

from services.blueprint.journeys import critical_journey_pages, critical_journey_routes
from services.blueprint.projection import (
    ENTITY_ALIASES_PATH, entity_alias_map, project_data_layer)
from services.runtime_injector import _generate_data_api_route, _generate_data_init_module
from services.smith.review_loop import run_review_loop


def _entities():
    return [
        {"id": "ENTITY-001", "name": "Patient", "table": "patients", "account": True,
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "fullName", "type": "string", "required": True}]},
        {"id": "ENTITY-002", "name": "Child", "table": "children",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "patientId", "type": "uuid", "required": True},
                    {"name": "name", "type": "string", "required": True}]},
        {"id": "ENTITY-003", "name": "Person", "table": "people",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]},
    ]


# ── A page asks for the entity by name; the schema exports the table ──────────

def test_every_entity_is_known_by_its_name_and_its_table():
    aliases = entity_alias_map(_entities())
    assert "Child" in aliases["children"] and "children" in aliases["child"]
    assert "Person" in aliases["people"] and "people" in aliases["person"]


def test_the_data_layer_tells_the_engine_every_name(tmp_path):
    doc = {"data": {"entities": _entities(), "relationships": []}}
    out = project_data_layer(doc, tmp_path)
    assert ENTITY_ALIASES_PATH in out["files"]
    ts = (tmp_path / ENTITY_ALIASES_PATH).read_text()
    assert '"child": ["Child", "children"' in ts


def test_registration_uses_the_names_a_blueprint_declares(tmp_path):
    """No legacy registry: the projection's file is what registration reads.
    Before, both registration sites fell back to the export name alone, and
    `list("Child")` was an unknown entity swallowed into an empty page."""
    doc = {"data": {"entities": _entities(), "relationships": []}}
    project_data_layer(doc, tmp_path)
    (tmp_path / "src" / "app" / "api" / "data" / "[...path]").mkdir(parents=True)
    _generate_data_init_module(tmp_path)
    init = (tmp_path / "src" / "lib" / "data-init.ts").read_text()
    assert 'import { aliasesFor } from "./entity-aliases";' in init
    assert "aliases: aliasesFor(name)" in init
    _generate_data_api_route(tmp_path)
    route = (tmp_path / "src" / "app" / "api" / "data" / "[...path]" / "route.ts").read_text()
    assert "aliases: aliasesFor(name)" in route


def test_assembly_keeps_the_projected_names():
    from services.blueprint.assembly import PROJECTED_PATHS
    assert ENTITY_ALIASES_PATH in PROJECTED_PATHS


def test_the_sample_reader_is_who_a_widget_filter_means():
    shim = (Path(__file__).resolve().parents[2] / "static" / "jit-samples.mjs").read_text()
    assert 'v === "$user.id" ? READER : v' in shim


# ── "Verify only the critical journeys" means something ─────────────────────

def _journey_doc():
    return {
        "pages": [
            {"id": "P-ADMIN", "route": "/admin", "entry": True, "users": ["ADMIN"]},
            {"id": "P-HOME", "route": "/", "entry": True, "users": ["PARENT"]},
            {"id": "P-KIDS", "route": "/children", "pattern": "entity_list",
             "data": {"primaryEntity": "E-CHILD"}, "users": ["PARENT"]},
            {"id": "P-ADD", "route": "/children/new", "users": ["PARENT"]},
            {"id": "P-ALLKIDS", "route": "/admin/children", "pattern": "entity_list",
             "data": {"primaryEntity": "E-CHILD"}, "users": ["ADMIN"]},
            {"id": "P-ABOUT", "route": "/about", "users": ["PARENT"]},
            {"id": "P-OLD", "route": "/old", "entry": True, "status": "DEPRECATED"},
        ],
        "workflows": [{
            "id": "FLOW-1", "launchedFrom": ["P-ADD"],
            "steps": [{"key": "insert", "entity": "E-CHILD",
                       "config": {"actionType": "db_insert", "table": "children"}}],
        }],
    }


def test_a_journey_is_where_people_land_start_work_and_read_it_back():
    assert critical_journey_pages(_journey_doc()) == ["P-ADMIN", "P-HOME", "P-KIDS", "P-ADD"]


def test_the_admins_list_is_not_on_the_parents_journey():
    assert "/admin/children" not in critical_journey_routes(_journey_doc())


def test_the_journeys_scope_the_verify():
    router = importlib.import_module("routers.blueprint_generate")
    routes = router._verify_scope("Verify only the critical journeys.", _journey_doc())
    assert routes == ["/admin", "/", "/children", "/children/new"]
    assert router._verify_scope("Verify the whole application — every page", _journey_doc()) is None


# ── One build of an application at a time ────────────────────────────────────

def _ledger(tmp_path: Path, events: list[dict]) -> Path:
    runs = tmp_path / ".forge" / "runs"
    runs.mkdir(parents=True)
    path = runs / "20260926-170052-aaaaaa.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


def test_a_second_build_is_not_started_on_a_running_one(tmp_path):
    router = importlib.import_module("routers.blueprint_generate")
    _ledger(tmp_path, [{"event": "run:start", "at": "2026-09-26T17:00:52Z"},
                       {"event": "plan", "nodes": ["a", "b", "c"]},
                       {"event": "node:done", "node": "a"}])
    said: list[tuple[str, dict]] = []
    out = router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True,
                          emit=lambda kind, data: said.append((kind, data)))
    assert out["status"] == "busy"
    assert "still being built — 1 of 3 steps done" in said[0][1]["text"]


def test_a_finished_or_dead_run_does_not_hold_the_app(tmp_path):
    router = importlib.import_module("routers.blueprint_generate")
    ended = _ledger(tmp_path, [{"event": "run:start", "at": "2026-09-26T17:00:52Z"},
                               {"event": "run:end", "at": "2026-09-26T17:28:07Z"}])
    assert router.build_in_flight(tmp_path) is None
    ended.write_text(json.dumps({"event": "run:start", "at": "2026-09-26T17:00:52Z"}) + "\n")
    old = time.time() - 600
    import os
    os.utime(ended, (old, old))
    assert router.build_in_flight(tmp_path) is None, "a ledger silent for ten minutes is a dead run"


# ── A check that cannot be made says why, and what to do ─────────────────────

def test_a_rebuild_that_could_not_be_checked_says_why():
    looks = iter([{"findings": [{"route": "/", "kind": "sparse", "severity": "warn",
                                 "note": "the list is empty"}]}, None])

    def critique():
        report = next(looks)
        critique.problem = None if report else "/: the preview did not render (502)"
        return report

    doc = {"pages": [{"id": "PAGE-001", "route": "/"}]}
    outcome = run_review_loop(read_doc=lambda: doc, critique=critique,
                              recompose_and_rebuild=lambda briefs: {})
    assert outcome.skipped == "the rebuilt app could not be rendered to check it"
    assert outcome.skipped_because == "/: the preview did not render (502)"


# ── "Rebuild" after a fix: the fix is already built ──────────────────────────

def test_rebuild_after_a_change_says_the_change_is_in_the_app(tmp_path):
    from services.smith4.verbs import Ctx, rebuild
    ctx = Ctx(output_dir=str(tmp_path), project_id="p", message="Fix this, rebuild and launch",
              ask="Fix this, rebuild and launch")
    ctx.applied.append("Changed Add Child (FLOW-002), recorded as DEC-005.")
    out = rebuild(ctx, {"verb": "rebuild"})
    assert out.status == "resolved"
    assert "already in the application" in out.said and "Publish" in out.said
    assert "Approve and build" not in out.said


def test_rebuild_with_nothing_changed_still_says_chat_changes_are_live(tmp_path):
    from services.smith4.verbs import Ctx, rebuild
    ctx = Ctx(output_dir=str(tmp_path), project_id="p", message="rebuild", ask="rebuild")
    out = rebuild(ctx, {"verb": "rebuild"})
    assert "Approve and build" in out.said
    assert "Publish carries them live without a rebuild" in out.said
