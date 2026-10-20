"""Chat-v2 handler — Migration Step 3.

The new single-entry point for the Smith-as-architect rewrite.
The architect is the path, not an option behind a flag; what used to be off
(the default) the handler returns a clear "not enabled" response
so no traffic accidentally routes here.

When the flag is on:
  1. Load the blueprint for the project.
  2. Run the chat router (services/smith_chat_router.py) to decide
     bootstrap / iteration / ask_user.
  3. Run the v4 turn (`services.smith4.handle`) and return a ChatV2Response.

This module is a PURE HANDLER (no FastAPI decorators, no SSE) so
tests exercise it directly. The FastAPI route that actually wires
it to the HTTP surface lives in `routers/chat_v2.py` and lands
alongside the live acceptance work (Migration Step 4). Keeping the
handler pure means the same code can serve both HTTP and CLI /
notebook / test contexts.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from typing import Any, Callable

from services.smith_blueprint import Blueprint
from services.smith_chat_router import ChatIntent, route_chat_message


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Flag
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Request / response shapes
# --------------------------------------------------------------------------- #

@dataclass
class ChatV2Request:
    project_id: str
    output_dir: str
    message: str
    #: Earlier turns as (role, text), oldest first. Empty is a first turn, not
    #: an error — and a caller that has no transcript (self-heal, cron) simply
    #: has none.
    history: list[tuple[str, str]] = field(default_factory=list)
    source: str = "user"
    #: Called with each reasoning chunk as it arrives, from the worker thread.
    #: The router hands in one that emits a `thought` event; a caller with
    #: nobody watching passes None and the model reasons privately, as before.
    reasoning_fn: Callable[[str], None] | None = None
    # For tests + gradual wiring: caller can override any SmithSession
    # seam. Prod passes {} and the handler wires the real defaults.
    session_overrides: dict[str, Callable[..., Any]] = field(default_factory=dict)
    #: Documents supplied with the ask, as text — a spec, a policy.
    evidence: list[str] = field(default_factory=list)
    #: What the project is called, for a Blueprint created on this turn.
    app_name: str = ""
    #: True when the caller posts the answer itself and runs the after-change
    #: check afterwards (`app_check.check_change`) as a second message.
    defer_check: bool = False
    #: The files attached to this message, as `chat_attachments.locate`
    #: records: the pictures are shown to the model, and verbs (`set_logo`)
    #: take theirs from here.
    attachments: list[dict] = field(default_factory=list)


@dataclass
class ChatV2Response:
    status: str          # "resolved" | "asked" | "needs_user" | "no_op" | "not_enabled" | "handoff"
    answer: str
    options: list[str] = field(default_factory=list)
    diff_summary: str = ""
    touched_paths: list[str] = field(default_factory=list)
    intent: str | None = None  # what the router decided
    follow_up: str = ""        # "run:<phase>" — the turn asks the router to run that phase again


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def handle_chat_v2(req: ChatV2Request) -> ChatV2Response:
    """The single handler. Pure function of the request + env; every
    downstream boundary is either injected or resolved from the
    process env."""

    blueprint = Blueprint.load(
        project_id=req.project_id, output_dir=req.output_dir,
    )

    intent: ChatIntent = route_chat_message(
        blueprint=blueprint, message=req.message, source=req.source,
    )

    if intent.kind == "ask_user":
        return ChatV2Response(
            status="asked", answer=intent.message, intent="ask_user",
        )

    # Bootstrap and iteration are the same turn since Smith v4: before there
    # is an application the loop's page says so and its moves are
    # `open_decisions` and `define_application`; after, the verbs. The router
    # still says which it decided, for the caller's bookkeeping.

    # `next_step_fn` (the chooser), `iteration_move_fn` and `guards_fn` still
    # win when injected, which is what keeps the handler testable.
    from services.smith4 import handle as smith4_handle
    overrides = req.session_overrides or {}
    out = smith4_handle(
        project_id=req.project_id, output_dir=req.output_dir,
        message=intent.message, history=req.history,
        choose=overrides.get("next_step_fn"),
        move=overrides.get("iteration_move_fn"),
        guards=overrides.get("guards_fn"),
        reasoning=req.reasoning_fn,
        evidence=list(req.evidence or []),
        attachments=list(req.attachments or []),
        app_name=req.app_name,
        check_after=not req.defer_check,
    )
    return ChatV2Response(status=out.status, answer=out.said, options=list(out.options),
                          diff_summary=out.diff_summary, touched_paths=list(out.touched),
                          intent=intent.kind, follow_up=str(getattr(out, "follow_up", "") or ""))


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

