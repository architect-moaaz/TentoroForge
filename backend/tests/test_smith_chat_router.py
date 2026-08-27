"""Smith chat router — the single-entry seam.

Spec §4.2 & §10.1: every user touchpoint should reach one function.
That function inspects the project's blueprint to decide which flow
runs (bootstrap vs iteration vs self-heal).

This slice ships the router as a *pure decision function* — no HTTP
wiring yet. S6/S7 plug the router into the actual bootstrap and
iteration handlers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.smith_blueprint import Blueprint
from services.smith_chat_router import (
    ChatIntent,
    route_chat_message,
)


def _empty_project(tmp_path: Path, project_id: str = "p1") -> Blueprint:
    bp = Blueprint.load(project_id=project_id, output_dir=str(tmp_path))
    return bp


def _project_with_domain(tmp_path: Path, project_id: str = "p1") -> Blueprint:
    bp = Blueprint.load(project_id=project_id, output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()
    return Blueprint.load(project_id=project_id, output_dir=str(tmp_path))


def test_bootstrap_intent_for_empty_project(tmp_path):
    """A project with no blueprint entries yet is in bootstrap. Any
    user message routes to the new-app flow (discovery → planner →
    generator)."""
    bp = _empty_project(tmp_path)
    intent = route_chat_message(
        blueprint=bp, message="Design an ATS for cabin crew recruitment",
        source="user",
    )
    assert intent.kind == "bootstrap"
    assert intent.message == "Design an ATS for cabin crew recruitment"


def test_iteration_intent_for_existing_project(tmp_path):
    """Once the domain is set, subsequent asks are iteration."""
    bp = _project_with_domain(tmp_path)
    intent = route_chat_message(
        blueprint=bp,
        message="In Add Candidate, upload CV is the dropdown",
        source="user",
    )
    assert intent.kind == "iteration"


def test_self_heal_source_is_iteration_even_on_bootstrap_state(tmp_path):
    """A runtime exception in the generated app is by definition an
    iteration — bootstrap has no running app to crash from."""
    bp = _empty_project(tmp_path)
    intent = route_chat_message(
        blueprint=bp, message="TypeError: cannot read x of undefined",
        source="self-heal",
    )
    assert intent.kind == "iteration"
    assert intent.trigger == "self-heal"


def test_editor_source_records_trigger(tmp_path):
    """Editor-followup chats (user clicked a field in the editor and
    asked Smith about it) are iteration + trigger=editor."""
    bp = _project_with_domain(tmp_path)
    intent = route_chat_message(
        blueprint=bp, message="explain what this field does",
        source="editor-followup",
    )
    assert intent.kind == "iteration"
    assert intent.trigger == "editor-followup"


def test_empty_message_becomes_ask_user_intent(tmp_path):
    """Whitespace-only messages don't reach the flow — the router
    short-circuits into a targeted ask_user."""
    bp = _empty_project(tmp_path)
    intent = route_chat_message(blueprint=bp, message="   ", source="user")
    assert intent.kind == "ask_user"
    assert intent.message


def test_unknown_source_defaults_to_user_trigger(tmp_path):
    bp = _project_with_domain(tmp_path)
    intent = route_chat_message(blueprint=bp, message="hi", source="something-new")
    assert intent.trigger == "user"


def test_intent_carries_project_id_for_downstream_handlers(tmp_path):
    bp = _project_with_domain(tmp_path, project_id="pXYZ")
    intent = route_chat_message(blueprint=bp, message="do X", source="user")
    assert intent.project_id == "pXYZ"
