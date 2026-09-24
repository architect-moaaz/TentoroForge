"""SmithSession — the architect's per-turn service.

Spec: `docs/superpowers/specs/2026-07-17-smith-as-architect.md`
sections §5, §7, §9, §10, §11.

The session is what the (future) POST /chat/message handler
instantiates for each turn. It ties together:

  * the Blueprint (Smith's memory)          — services/smith_blueprint.py
  * the context renderer                    — services/smith_blueprint_context.py
  * ground-truth verification               — services/ground_truth.py
  * narrator artifacts from internal agents — services/narrator_artifacts.py

Every external boundary is an injectable seam. Tests supply stubs;
production wiring lands later slices with the real discovery /
planner / generator adapters plus the actual understand_ask + move
implementations.

Public surface:

  * :func:`SmithSession(project_id, output_dir, ...seams)` — new.
  * :meth:`run_bootstrap(user_message)` → :class:`TurnResult`.
    Full new-app flow: discovery → planner → generator → blueprint
    write → committed change_log entry.
  * :meth:`run_iteration(user_message)` → :class:`TurnResult`.
    Extract intent → run the move → verify against ground truth →
    resolve or ask user. Ground-truth-only means Smith's self-report
    is never trusted; the diff Smith is credited for is the actual
    git diff of the working tree.

Failure semantics (§11):
  * No silent rollback on iteration failure. Session returns
    ``status='needs_user'`` with a specific message + a list of
    ``options`` for the user to pick.
  * Bootstrap failures raise from the seams (the caller decides).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from services.smith_blueprint import Blueprint
from services.smith_blueprint_context import blueprint_to_context
from services.narrator_artifacts import (
    DiscoveryArtifact,
    PlannerArtifact,
    GeneratorArtifact,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Result shapes
# --------------------------------------------------------------------------- #

@dataclass
class IterationMove:
    """What the iteration move function returns to the session.

    Not a self-report of what changed — a *label* naming the move
    Smith intended. The actual "what changed" comes from git."""
    move_name: str
    touched_paths: list[str] = field(default_factory=list)


@dataclass
class TurnResult:
    """Everything a chat turn produces for the caller.

    ``status`` in {"resolved", "asked", "needs_user", "no_op"}:
      * ``resolved``   — move landed, verified, blueprint updated.
      * ``asked``      — Smith emitted a clarifying question.
      * ``needs_user`` — a hard failure that the user must resolve
                         (choose from ``options``). No silent
                         rollback.
      * ``no_op``      — Smith read but didn't need to change
                         anything.

    ``finding`` separates the two things ``needs_user`` had come to mean. A
    FINDING is something the platform PROVED about the work it just did — git
    says the diff did not touch the file that was named, the composer laid the
    page out without what it was told to put on it, a guard that passed now
    fails. A question for the person is not a finding: "I do not recognise
    that", "building runs from the card", "are you sure — this deletes a
    column" are asks, and no amount of thinking makes them answerable without
    them.

    The distinction is the whole of `2026-09-24-smith-as-a-loop` §4.4. A
    finding is evidence, and evidence is exactly what a second step can act on:
    "I edited X but you asked about Y" is the sentence that makes a model try
    the other reading. Handed to the person instead, with three chips, it is a
    dead end at the end of four minutes' work. The text is written for the
    thing that reads it next, not for the chat bubble — ``answer`` is still
    what the person sees.
    """
    status: str
    answer: str
    options: list[str] = field(default_factory=list)
    diff_summary: str = ""
    touched_paths: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    #: What an oracle proved about this step, in its own words. "" when the
    #: outcome is a question rather than a proof.
    finding: str = ""


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #

# Type aliases for readability.
DiscoveryFn = Callable[[str, str], DiscoveryArtifact]
PlannerFn = Callable[[DiscoveryArtifact], PlannerArtifact]
GeneratorFn = Callable[[PlannerArtifact, str], GeneratorArtifact]
GuardsFn = Callable[[str], list[dict[str, Any]]]


class SmithSession:
    """One architect-conversation, backed by the blueprint on disk."""

    def __init__(
        self, *,
        project_id: str,
        output_dir: str,
        discovery_fn: DiscoveryFn | None = None,
        planner_fn: PlannerFn | None = None,
        generator_fn: GeneratorFn | None = None,
        guards_fn: GuardsFn | None = None,
        reasoning_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.project_id = project_id
        self.output_dir = output_dir
        # Seams
        self._discovery = discovery_fn
        self._planner = planner_fn
        self._generator = generator_fn
        self._guards = guards_fn or (lambda _out: [])
        # Where Smith's reasoning goes so the user can read it. None means
        # nobody is watching, which is every caller that predates it.
        self._reasoning = reasoning_fn

    # ---- Bootstrap flow (§5.1) ------------------------------------------

    def run_bootstrap(self, user_message: str) -> TurnResult:
        """Discovery → planner → generator, with blueprint writes at
        each step. The three seams MUST be wired; a real caller
        that skips them gets an assertion (bootstrap can't happen
        without them)."""
        assert self._discovery and self._planner and self._generator, (
            "bootstrap requires discovery_fn + planner_fn + generator_fn"
        )
        bp = Blueprint.load(project_id=self.project_id, output_dir=self.output_dir)
        blueprint_ctx = blueprint_to_context(bp)

        discovery = self._discovery(user_message, blueprint_ctx)
        bp.set_domain(
            name=discovery.domain_name,
            primary_actors=discovery.actors,
            core_verbs=discovery.verbs,
            distinctive_shape=discovery.distinctive_shape,
            why=user_message,
        )
        bp.save()

        plan = self._planner(discovery)
        for e in plan.entities:
            bp.add_entity(
                name=e.name, table=e.table, purpose=e.purpose,
                key_fields=e.key_fields,
                why_shaped_this_way=e.why_shaped_this_way,
            )
        for w in plan.workflows:
            bp.add_workflow(name=w.name, purpose=w.purpose,
                            trigger=w.trigger, why=w.why)
        for p in plan.pages:
            bp.add_page(route=p.route, schema_path=p.schema_path,
                        role=p.role, notable_choices=[])
        bp.save()

        gen = self._generator(plan, self.output_dir)

        answer_parts = [
            discovery.narrator_summary(),
            plan.narrator_summary(),
            gen.narrator_summary(),
        ]
        answer = "\n\n".join(a for a in answer_parts if a)

        # Change log entry for the whole bootstrap turn.
        bp.append_change_log(
            at=_now_iso(), user_ask=user_message,
            smith_move="bootstrap: discovery → planner → generator",
            diff_summary=f"{len(gen.generated_files)} file(s) generated",
            verified_by=["discovery+planner+generator narrator artifacts"],
            why=discovery.domain_name,
            source="smith",
        )
        bp.save()

        return TurnResult(
            status="resolved",
            answer=answer,
            touched_paths=list(gen.generated_files),
            diff_summary=f"generated {len(gen.generated_files)} file(s)",
        )


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
