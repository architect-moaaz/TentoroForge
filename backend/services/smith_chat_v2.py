"""Chat-v2 handler — Migration Step 3.

The new single-entry point for the Smith-as-architect rewrite.
Behind the ``FORGE_SMITH_ARCHITECT=1`` flag; when the flag is off
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
from typing import Any, Callable

from services.smith_blueprint import Blueprint
from services.smith_chat_router import ChatIntent, route_chat_message
from services.smith_session import SmithSession, TurnResult


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Flag
# --------------------------------------------------------------------------- #

def architect_flag_enabled() -> bool:
    """Truthy unless ``FORGE_SMITH_ARCHITECT=0`` explicitly disables it.

    Default is ON — the architect stack is the primary path. Set
    ``FORGE_SMITH_ARCHITECT=0`` to force-fall-back to the tactical
    Smith while the architect stack is still being hardened."""
    return os.environ.get("FORGE_SMITH_ARCHITECT", "1").strip() != "0"


# --------------------------------------------------------------------------- #
# Request / response shapes
# --------------------------------------------------------------------------- #

@dataclass
class ChatV2Request:
    project_id: str
    output_dir: str
    message: str
    source: str = "user"
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
    if not architect_flag_enabled():
        return ChatV2Response(
            status="not_enabled",
            answer=(
                "Smith-as-architect handler is not enabled on this backend. "
                "Set `FORGE_SMITH_ARCHITECT=1` to route through the new flow."
            ),
        )

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
        result = session.run_iteration(user_message=intent.message)
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
        understand_ask_fn=overrides.get("understand_ask_fn"),
        iteration_move_fn=overrides.get("iteration_move_fn"),
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
