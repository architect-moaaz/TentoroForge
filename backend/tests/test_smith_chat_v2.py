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

def test_an_undefined_project_gets_the_same_turn_with_the_definition_page(tmp_path):
    """No discovery/planner/generator seams: before there is an application
    the loop's page says so and the chooser's moves are the definition ones."""
    seen: dict = {}

    def choose(ask, page, observations, history):
        seen["page"] = page
        return {"tool": "ask_user", "args": {"question": "Who uses it?", "options": ["Recruiters", "Candidates"]}, "why": ""} \
            if any(o.status == "error" for o in observations) else {"tool": "ask_user", "args": {"question": "Who uses it?"}, "why": ""}

    req = ChatV2Request(
        project_id="p1", output_dir=str(tmp_path),
        message="build me an ATS", source="user",
        session_overrides={"next_step_fn": choose, "iteration_move_fn": lambda u, out: None},
    )
    r = handle_chat_v2(req)
    assert r.intent == "bootstrap" and r.status == "asked"
    assert "THERE IS NO APPLICATION YET" in seen["page"] and "build me an ATS" in seen["page"]


def test_flag_on_iteration_asks_when_the_chooser_asks(tmp_path, monkeypatch):
    """A project past bootstrap + ambiguous ask ⇒ ask_user.

    Smith v4: there is no `understand_ask_fn`; the chooser is the seam. Its
    first question is sent to look (nothing has been read), its second stands.
    """
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()

    req = ChatV2Request(
        project_id="p1", output_dir=str(tmp_path),
        message="fix it", source="user",
        session_overrides={
            "next_step_fn": lambda ask, page, seen, history: {
                "tool": "ask_user", "args": {"question": "Which page were you on?"}, "why": "",
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
