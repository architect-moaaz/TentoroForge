"""Chat-v2 handler — Migration Step 3.

The new single-entry point for the Smith-as-architect rewrite.
The architect is the path, not an option behind a flag; what used to be off
(the default) the handler returns a clear "not enabled" response
so no traffic accidentally routes here.

When the flag is on:
  1. Load the blueprint for the project.
  2. Run the chat router (services/smith_chat_router.py) to decide
     bootstrap / iteration / ask_user.
  3. Instantiate SmithSession with the real (or test-injected)
     seams.
  4. Run the chosen flow, return a ChatV2Response.

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

from services.smith.move_dispatcher import move_dispatcher
from services.smith.understand_ask import understand_ask
from typing import Any, Callable

from services.smith_blueprint import Blueprint
from services.smith_chat_router import ChatIntent, route_chat_message
from services.smith_session import SmithSession, TurnResult


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


@dataclass
class ChatV2Response:
    status: str          # "resolved" | "asked" | "needs_user" | "no_op" | "not_enabled" | "handoff"
    answer: str
    options: list[str] = field(default_factory=list)
    diff_summary: str = ""
    touched_paths: list[str] = field(default_factory=list)
    intent: str | None = None  # what the router decided


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

    session = _build_session(req, blueprint)

    if intent.kind == "bootstrap":
        try:
            result = session.run_bootstrap(user_message=intent.message)
        except AssertionError as exc:
            return _seams_missing("bootstrap", str(exc))
        return _to_response(result, intent="bootstrap")

    # kind == "iteration"
    try:
        result = session.run_iteration(
        user_message=intent.message, history=req.history,
    )
    except AssertionError as exc:
        return _seams_missing("iteration", str(exc))
    return _to_response(result, intent="iteration")


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _build_session(
    req: ChatV2Request, blueprint: Blueprint,
) -> SmithSession:
    """Compose a SmithSession from request overrides + prod defaults.

    Overrides win. Any seam not provided AND not wired at the module
    level surfaces at flow-time as an AssertionError, which the
    handler converts to a `not_enabled_seam` response."""
    overrides = req.session_overrides or {}
    return SmithSession(
        project_id=req.project_id,
        output_dir=req.output_dir,
        discovery_fn=overrides.get("discovery_fn"),
        planner_fn=overrides.get("planner_fn"),
        generator_fn=overrides.get("generator_fn"),
        guards_fn=overrides.get("guards_fn"),
        # Wired, where the other seams are still None. `run_iteration` has
        # always handled a clarification — it short-circuits to
        # status="asked" — and had nothing feeding it, so §16's gate existed
        # and never fired. An override still wins, which is what keeps the
        # handler testable without a model.
        understand_ask_fn=overrides.get("understand_ask_fn") or understand_ask,
        # The move writes, so `run_iteration` verifies it against git rather
        # than believing it. Wired here; overrides still win, which is how the
        # handler stays testable without touching a filesystem.
        iteration_move_fn=overrides.get("iteration_move_fn") or move_dispatcher,
        reasoning_fn=req.reasoning_fn,
    )


def _to_response(result: TurnResult, *, intent: str) -> ChatV2Response:
    return ChatV2Response(
        status=result.status, answer=result.answer,
        options=list(result.options),
        diff_summary=result.diff_summary,
        touched_paths=list(result.touched_paths),
        intent=intent,
    )


def _seams_missing(flow: str, detail: str) -> ChatV2Response:
    """Prod wiring for {discovery,planner,generator,understand,move}
    seams lands in Migration Step 4 (live acceptance). Until then
    the handler surfaces a specific message so the caller sees
    exactly what's not wired instead of a 500."""
    return ChatV2Response(
        status="not_enabled",
        answer=(
            f"The {flow} flow needs seams that aren't wired yet on this "
            "backend. Live orchestrators for discovery / planner / "
            "generator / understand_ask / move_dispatcher land in "
            f"Migration Step 4. Detail: {detail}"
        ),
    )
