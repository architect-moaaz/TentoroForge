"""Chat-v2 handler scaffold — Migration Step 3.

The new HTTP entry point behind FORGE_SMITH_ARCHITECT=1. When the
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
    architect_flag_enabled,
)


# --------------------------------------------------------------------------- #
# Flag gate
# --------------------------------------------------------------------------- #

def test_architect_flag_defaults_on(monkeypatch):
    """As of Migration Step 4b the architect stack is the primary
    path — unset means enabled."""
    monkeypatch.delenv("FORGE_SMITH_ARCHITECT", raising=False)
    assert architect_flag_enabled() is True


def test_architect_flag_on_when_env_is_1(monkeypatch):
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "1")
    assert architect_flag_enabled() is True


def test_architect_flag_off_only_when_explicit_zero(monkeypatch):
    """Explicit "0" disables (tactical-Smith escape hatch). Other
    values are treated as enabled (fail-forward to the new path)."""
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "0")
    assert architect_flag_enabled() is False

    for v in ("1", "true", "yes", "on", ""):
        monkeypatch.setenv("FORGE_SMITH_ARCHITECT", v)
        assert architect_flag_enabled() is True, f"{v!r} should enable"


# --------------------------------------------------------------------------- #
# handle_chat_v2 — flag off
# --------------------------------------------------------------------------- #

def test_flag_off_returns_not_enabled_response(tmp_path, monkeypatch):
    """Explicit FORGE_SMITH_ARCHITECT=0 disables (tactical escape hatch)."""
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "0")
    req = ChatV2Request(
        project_id="p1", output_dir=str(tmp_path),
        message="hi", source="user",
    )
    r = handle_chat_v2(req)
    assert r.status == "not_enabled"
    assert "FORGE_SMITH_ARCHITECT" in r.answer


# --------------------------------------------------------------------------- #
# handle_chat_v2 — flag on, routing works end-to-end
# --------------------------------------------------------------------------- #

def test_flag_on_bootstrap_routes_to_bootstrap_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "1")

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
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "1")
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
    monkeypatch.setenv("FORGE_SMITH_ARCHITECT", "1")
    req = ChatV2Request(
        project_id="p1", output_dir=str(tmp_path),
        message="   ", source="user",
    )
    r = handle_chat_v2(req)
    assert r.status == "asked"
