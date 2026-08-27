"""Smith chat router — the single-entry seam.

Spec: §4.2 & §10.1.

Today the backend has one route for bootstrap generation (`/generate/*`)
and another for chat fixes (`/chat/*`). The Smith-as-architect
rewrite collapses both into one entry: every user touchpoint
inspects the project's blueprint and decides which flow to run.

This module ships that decision as a pure function. HTTP wiring
happens later (S6 for bootstrap, S7 for iteration). Keeping the
decision as data lets tests exercise every branch without spinning
up a real request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.smith_blueprint import Blueprint


# --------------------------------------------------------------------------- #
# Recognized sources
# --------------------------------------------------------------------------- #

_KNOWN_SOURCES = frozenset({"user", "self-heal", "editor-followup"})


@dataclass(frozen=True)
class ChatIntent:
    """The decision this router makes for one incoming chat turn.

    ``kind`` in {"bootstrap", "iteration", "ask_user"}:
      * ``bootstrap``   — new-app flow (discovery/planner/generator).
      * ``iteration``   — targeted move against an existing app.
      * ``ask_user``    — router refused the message (empty text
                          etc.); Smith should ask a specific
                          clarifying question.

    ``trigger`` names *why* the message arrived — the router only
    passes it through; downstream handlers use it for logging,
    telemetry, and UX labeling (self-heal chips vs regular chat).
    """
    kind: str
    project_id: str
    message: str
    trigger: str
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def route_chat_message(
    *,
    blueprint: Blueprint,
    message: str,
    source: str,
) -> ChatIntent:
    """Decide which flow a chat message belongs to.

    Pure function — the caller supplies the blueprint (already
    loaded from disk) and gets back the decision. No side effects,
    no I/O.
    """
    trigger = source if source in _KNOWN_SOURCES else "user"
    text = (message or "").strip()

    if not text:
        return ChatIntent(
            kind="ask_user",
            project_id=blueprint.project_id,
            message="What would you like me to work on? A one-line description "
                    "of the screen or behavior is enough for me to get started.",
            trigger=trigger,
        )

    # Self-heal is always iteration (a runtime error implies a
    # running app, i.e. we're past bootstrap even if the blueprint
    # hasn't caught up).
    if trigger == "self-heal":
        return ChatIntent(
            kind="iteration", project_id=blueprint.project_id,
            message=text, trigger=trigger,
        )

    # Otherwise: bootstrap iff the project has no domain yet.
    if _is_bootstrap_state(blueprint):
        return ChatIntent(
            kind="bootstrap", project_id=blueprint.project_id,
            message=text, trigger=trigger,
        )

    return ChatIntent(
        kind="iteration", project_id=blueprint.project_id,
        message=text, trigger=trigger,
    )


def _is_bootstrap_state(bp: Blueprint) -> bool:
    """A project is in bootstrap iff no domain was ever set.

    Rationale: the domain is the first thing discovery writes. Any
    project that has a domain is past bootstrap — even if it has
    zero entities yet, Smith should be iterating on the plan, not
    starting discovery from scratch."""
    return bp.domain is None or not bp.domain
