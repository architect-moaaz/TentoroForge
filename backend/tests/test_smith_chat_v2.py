"""Chat-v2 handler scaffold — Migration Step 3.

The architect's single handler. It used to sit behind a flag; when the
flag is off (default), returns a clear "not enabled" response so
existing traffic never accidentally routes here. When the flag is
on, dispatches via SmithChatRouter to either SmithSession's
bootstrap or iteration flow.

The tests exercise the request/response shape + the flag gate.
Real LLM wiring is provided via injectable seams so we don't need
API credentials to test the plumbing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.smith_blueprint import Blueprint
from services.smith_chat_v2 import (
    ChatV2Request,
    ChatV2Response,
    handle_chat_v2,
)


# --------------------------------------------------------------------------- #
# Flag gate
# --------------------------------------------------------------------------- #

def test_flag_on_bootstrap_routes_to_bootstrap_flow(tmp_path, monkeypatch):

    from services.narrator_artifacts import (
        DiscoveryArtifact, PlannerArtifact, GeneratorArtifact,
    )

    called = {}
    def _discovery(msg, ctx):
        called["discovery"] = True
        return DiscoveryArtifact.from_dict({
            "domain_name": "ATS", "actors": ["r"], "verbs": ["a"],
            "distinctive_shape": "kanban",
            "proposed_entities": [], "open_questions": [],
        })
    def _planner(d):
        called["planner"] = True
        return PlannerArtifact.from_dict({
            "entities": [{"name": "X", "table": "xs", "purpose": "",
                          "key_fields": [], "why_shaped_this_way": ""}],
            "workflows": [], "pages": [],
        })
    def _generator(p, out):
        called["generator"] = True
        return GeneratorArtifact.from_dict({
            "generated_files": ["src/schemas/x/index.json"],
            "warnings": [], "notes": [],
        })

    req = ChatV2Request(
        project_id="p1", output_dir=str(tmp_path),
        message="build me an ATS", source="user",
        session_overrides={
            "discovery_fn": _discovery,
            "planner_fn": _planner,
            "generator_fn": _generator,
        },
    )
    r = handle_chat_v2(req)
    assert r.status == "resolved"
    assert called == {"discovery": True, "planner": True, "generator": True}
    assert "ATS" in r.answer


def test_flag_on_iteration_asks_when_understand_returns_clarification(
    tmp_path, monkeypatch,
):
    """A project past bootstrap + ambiguous ask ⇒ ask_user."""
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()

    req = ChatV2Request(
        project_id="p1", output_dir=str(tmp_path),
        message="fix it", source="user",
        session_overrides={
            "understand_ask_fn": lambda m, ctx: {
                "clarification_needed": "which page were you on?",
            },
            "iteration_move_fn": lambda u, out: None,
        },
    )
    r = handle_chat_v2(req)
    assert r.status == "asked"
    assert "which page" in r.answer.lower()


def test_flag_on_empty_message_short_circuits_to_ask(tmp_path, monkeypatch):
    req = ChatV2Request(
        project_id="p1", output_dir=str(tmp_path),
        message="   ", source="user",
    )
    r = handle_chat_v2(req)
    assert r.status == "asked"
