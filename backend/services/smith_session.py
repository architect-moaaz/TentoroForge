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
from services.smith_blueprint_context import (
    blueprint_to_context,
    pick_relevant_slice,
)
from services.ground_truth import (
    git_status_modified,
    git_diff_lines,
    guard_delta,
    snapshot_baseline,
)
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
    """
    status: str
    answer: str
    options: list[str] = field(default_factory=list)
    diff_summary: str = ""
    touched_paths: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #

# Type aliases for readability.
DiscoveryFn = Callable[[str, str], DiscoveryArtifact]
PlannerFn = Callable[[DiscoveryArtifact], PlannerArtifact]
GeneratorFn = Callable[[PlannerArtifact, str], GeneratorArtifact]
GuardsFn = Callable[[str], list[dict[str, Any]]]
UnderstandFn = Callable[[str, str], dict[str, Any]]
MoveFn = Callable[[dict[str, Any], str], Optional[IterationMove]]


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
        understand_ask_fn: UnderstandFn | None = None,
        iteration_move_fn: MoveFn | None = None,
    ) -> None:
        self.project_id = project_id
        self.output_dir = output_dir
        # Seams
        self._discovery = discovery_fn
        self._planner = planner_fn
        self._generator = generator_fn
        self._guards = guards_fn or (lambda _out: [])
        self._understand = understand_ask_fn
        self._move = iteration_move_fn

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

    # ---- Iteration flow (§5.2 / §7 / §11) -------------------------------

    def run_iteration(self, user_message: str) -> TurnResult:
        """Ground-truth-verified iteration.

        Contract:
          1. Snapshot baseline (git status + guards) — the reference
             everything is diffed against.
          2. Extract intent via ``understand_ask_fn``. Low-confidence
             / missing target ⇒ escalate to ask_user immediately.
          3. Call the move function. It writes to disk.
          4. Ask git what actually changed. NOT Smith's self-report.
          5. Verify: diff mentions element_label, target_file in the
             modified set, guard_delta is empty.
          6. Any check fails ⇒ status='needs_user' with options.
        """
        assert self._understand and self._move, (
            "iteration requires understand_ask_fn + iteration_move_fn"
        )

        bp = Blueprint.load(project_id=self.project_id, output_dir=self.output_dir)
        blueprint_slice = pick_relevant_slice(bp, ask=user_message)
        blueprint_ctx = blueprint_to_context(blueprint_slice)

        baseline = snapshot_baseline(self.output_dir, guards_fn=self._guards)

        understanding = self._understand(user_message, blueprint_ctx) or {}
        clarification = (understanding.get("clarification_needed") or "").strip()
        if clarification:
            return TurnResult(status="asked", answer=clarification)

        target_file = (understanding.get("target_file") or "").strip()
        element_label = (understanding.get("element_label") or "").strip()
        if not target_file:
            return TurnResult(
                status="asked",
                answer="I need one more detail — which file or screen "
                       "should I edit? A route path or a screen name works.",
            )

        move = self._move(understanding, self.output_dir)
        if move is None:
            return TurnResult(
                status="no_op",
                answer="I looked at what you asked and I don't see anything "
                       "to change — the current state already matches. If "
                       "that surprises you, let me know what's off from your side.",
            )

        # Ground truth: what did git actually see change?
        modified_now = set(git_status_modified(self.output_dir))
        # Baseline may have had uncommitted changes; only NEW ones this
        # turn count as Smith's.
        baseline_status = set(baseline.get("status") or [])
        actually_touched = sorted(modified_now - baseline_status)

        if not actually_touched:
            return TurnResult(
                status="needs_user",
                answer=(
                    f"I tried the move `{move.move_name}` but nothing "
                    "actually changed on disk. Something short-circuited "
                    "before the write. Do you want me to retry with a "
                    "different approach or hand this back to you?"
                ),
                options=["retry with a different approach",
                         "let me investigate further",
                         "leave it and I'll come back later"],
            )

        # Diff-based checks.
        diff = git_diff_lines(self.output_dir, actually_touched)

        # Target-file check: is target_file in the actual set?
        touched_lower = {p.lower() for p in actually_touched}
        target_lower = target_file.lower()
        target_in_diff = any(
            target_lower in p or p in target_lower for p in touched_lower
        )
        if not target_in_diff:
            return TurnResult(
                status="needs_user",
                answer=(
                    f"I edited {actually_touched} but you asked about "
                    f"`{target_file}`. That's the wrong file. "
                    "Do you want me to retry against the correct file, "
                    "or roll this back and try a different approach?"
                ),
                options=["retry against the correct file",
                         "roll back and try again",
                         "keep this edit anyway"],
                diff_summary=_diff_summary_line(actually_touched, diff),
                touched_paths=list(actually_touched),
            )

        # Element-label check: does the diff mention the label?
        if element_label and element_label.lower() not in diff.lower():
            return TurnResult(
                status="needs_user",
                answer=(
                    f"I edited `{target_file}` but the diff doesn't touch "
                    f"anything labeled '{element_label}'. Looks like I "
                    "changed a nearby field instead. Retry?"
                ),
                options=["retry — target the correct element",
                         "roll back and try again",
                         "keep this edit anyway"],
                diff_summary=_diff_summary_line(actually_touched, diff),
                touched_paths=list(actually_touched),
            )

        # Guard delta.
        after_guards = self._guards(self.output_dir) or []
        new_failures = guard_delta(baseline.get("guards"), after_guards)
        if new_failures:
            summary = "; ".join(
                f"{f.get('guard') or '?'}: {f.get('message') or '?'}"
                for f in new_failures[:3]
            )
            return TurnResult(
                status="needs_user",
                answer=(
                    f"The edit landed on `{target_file}` but broke {len(new_failures)} "
                    f"guard(s): {summary}. What would you like to do?"
                ),
                options=["retry with the guard feedback",
                         "roll back this edit",
                         "keep it — I'll deal with the guards later"],
                diff_summary=_diff_summary_line(actually_touched, diff),
                touched_paths=list(actually_touched),
            )

        # All checks pass — record the win.
        summary_line = _diff_summary_line(actually_touched, diff)
        bp.append_change_log(
            at=_now_iso(),
            user_ask=user_message,
            smith_move=move.move_name,
            diff_summary=summary_line,
            verified_by=["git status", "git diff", "guard delta empty"],
            why=(understanding.get("desired_behavior") or "").strip()
                or "matches user ask",
            source="smith",
        )
        bp.save()

        answer = (
            f"Done. Changed `{target_file}` — "
            f"{(understanding.get('current_behavior') or 'previous state').strip()}"
            f" → {(understanding.get('desired_behavior') or 'requested change').strip()}."
        )
        return TurnResult(
            status="resolved",
            answer=answer,
            diff_summary=summary_line,
            touched_paths=list(actually_touched),
        )


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _diff_summary_line(paths: list[str], diff: str) -> str:
    """Compact one-liner Smith writes into change_log.diff_summary."""
    n = len(paths)
    if not diff:
        return f"{n} file(s) touched"
    added = diff.count("\n+") - diff.count("\n+++")
    removed = diff.count("\n-") - diff.count("\n---")
    files = ", ".join(paths[:3])
    if n > 3:
        files += f", +{n - 3} more"
    return f"{files} | +{added} -{removed}"
