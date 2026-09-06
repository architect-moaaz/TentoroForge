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
        reasoning_fn: Callable[[str], None] | None = None,
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

    # ---- Iteration flow (§5.2 / §7 / §11) -------------------------------

    def _connect_uxpilot(self, understanding: dict) -> "TurnResult":
        """Attach a UX Pilot page, having asked for the page and a variable NAME.

        The twin of :meth:`_connect_figma`; the same §42 rule and the same
        output, a `designSources` record for `figma_intelligence` to fan out
        over.
        """
        from services.smith.uxpilot_connect import UxPilotConnectError, connect
        from services.uxpilot.url import parse as _parse_ref

        page_ref = (understanding.get("uxpilot_ref") or "").strip()
        key_env = (understanding.get("key_env") or "").strip()

        if not page_ref:
            return TurnResult(
                status="asked",
                answer="Which UX Pilot page? Paste the page's URL or its id and "
                       "I'll pull the designs and theme out of it.",
            )
        if not key_env:
            return TurnResult(
                status="asked",
                answer=("Which environment variable holds your UX Pilot API key? "
                        "I need the NAME — `UXPILOT_API_KEY`, for example — not "
                        "the key itself. Anything you type here is written to "
                        "the conversation log, so a credential must not go in "
                        "it; add it under Settings → Integrations → UX Pilot "
                        "and tell me what it is called."),
            )
        if _parse_ref(page_ref) is None:
            return TurnResult(
                status="needs_user",
                answer=(f"That does not look like a UX Pilot page: {page_ref!r}. "
                        f"I need the page id, or the page's URL from UX Pilot."),
            )

        from services.smith.understand_ask import _design_scope

        treat_as = _design_scope(understanding.get("treat_as"))
        if not treat_as:
            return TurnResult(
                status="asked",
                answer=("Before I pull it in — is this design the "
                        "SPECIFICATION or a REFERENCE?\n\n"
                        "• Specification: I build exactly the screens on the page "
                        "and nothing else.\n"
                        "• Reference: the screens become requirements and the "
                        "design language, and the application is built around "
                        "them — usually more pages than designs.\n\n"
                        "Say “specification” or “reference”."),
            )

        try:
            out = connect(self.output_dir, uxpilot_ref=page_ref, key_env=key_env,
                          treat_as=treat_as)
        except UxPilotConnectError as exc:
            return TurnResult(status="needs_user", answer=str(exc))
        except Exception as exc:  # noqa: BLE001 — a turn reports, never crashes
            logger.exception("uxpilot connect failed for %s", self.output_dir)
            return TurnResult(
                status="needs_user",
                answer=f"I could not read that UX Pilot page: {type(exc).__name__}.",
            )
        return TurnResult(status="resolved", answer=out["summary"])

    def _connect_figma(self, understanding: dict) -> "TurnResult":
        """Attach a Figma design, having asked for a URL and a variable NAME.

        SMITH NEVER ASKS FOR THE TOKEN. §42 lists `chat history` first among the
        places a raw credential must not come to rest, and this conversation is
        written to disk. `services.figma.credentials` settled the shape before
        this method existed: a `FigmaCredential` holds a REFERENCE — the name of
        an environment variable — and the gateway resolves the secret at the
        moment of the call. A name is not a secret, so it can be asked for,
        stored and echoed; the token is never held at all.

        The extraction is evidence, not the application (§48-§51). What it
        produces is a `designSources` record for `figma_intelligence` to fan out
        over, and the run that follows is the ordinary DAG.
        """
        from services.smith.figma_connect import FigmaConnectError, connect

        url = (understanding.get("figma_url") or "").strip()
        token_env = (understanding.get("token_env") or "").strip()

        if not url:
            return TurnResult(
                status="asked",
                answer="Which Figma file? Paste the link from Figma's Share "
                       "dialog and I'll pull the screens and tokens out of it.",
            )
        if not token_env:
            # The ask names the shape of the answer, because the obvious reply
            # to "I need your Figma token" is to paste one — and that is the
            # outcome this whole path exists to avoid.
            return TurnResult(
                status="asked",
                answer=("Which environment variable holds your Figma token? I "
                        "need the NAME — `FIGMA_TOKEN`, for example — not the "
                        "token itself. Anything you type here is written to "
                        "the conversation log, so a credential must not go in "
                        "it; export the token in the backend's environment and "
                        "tell me what you called it."),
            )

        # THE CHEAP CHECK STAYS FIRST. Asking which kind of design this is
        # before knowing it IS one answers a mistyped link with a question about
        # scope — the same ordering mistake the URL check was moved forward to
        # fix, reintroduced one question later.
        from services.figma.url import parse as _parse_figma_url

        if _parse_figma_url(url) is None:
            return TurnResult(
                status="needs_user",
                answer=(f"That does not look like a Figma URL: {url!r}. I need "
                        f"the link from Figma's Share dialog, like "
                        f"https://figma.com/design/<key>/<name>?node-id=1-2"),
            )

        from services.smith.understand_ask import _design_scope

        treat_as = _design_scope(understanding.get("treat_as"))
        if not treat_as:
            # ASKED ONCE, BECAUSE THE TWO ANSWERS BUILD DIFFERENT APPLICATIONS.
            # Evidence derives the page set from the data model with the design
            # informing it — one real dashboard produced thirteen pages that way,
            # every one a fair reading of what a dashboard implies. Specification
            # builds the frames and nothing else. Guessing either way is a whole
            # application's shape decided silently.
            return TurnResult(
                status="asked",
                answer=("Before I pull it in — is this design the "
                        "SPECIFICATION or a REFERENCE?\n\n"
                        "• Specification: I build exactly the screens you drew "
                        "and nothing else. No sign-in, no lists behind the "
                        "numbers, no forms to create what they show, unless "
                        "they are in the file.\n"
                        "• Reference: the screens become requirements and the "
                        "design language, and the application is built around "
                        "them — usually more pages than frames.\n\n"
                        "Say “specification” or “reference”."),
            )

        try:
            out = connect(self.output_dir, figma_url=url, token_env=token_env,
                          treat_as=treat_as)
        except FigmaConnectError as exc:
            # Every message on this path names the reference or the failure
            # kind; `FigmaGatewayError` redacts its own detail (§42).
            return TurnResult(status="needs_user", answer=str(exc))
        except Exception as exc:  # noqa: BLE001 — a turn reports, never crashes
            logger.exception("figma connect failed for %s", self.output_dir)
            return TurnResult(
                status="needs_user",
                answer=f"I could not read that Figma file: {type(exc).__name__}.",
            )

        return TurnResult(status="resolved", answer=out["summary"])

    def _compose(self, verb: str, understanding: dict,
                 user_message: str) -> "TurnResult":
        """Compose a screen, or add sections to one, through the real agent.

        `services.smith.compose.run` builds the same TaskSpec the orchestrator
        builds and hands it to the same executor, so a page Smith composes and
        a page the build composed come from one code path — then commits it
        through `apply_change` so the Blueprint stays the record.

        THE SAME FUNCTION THE TOOL CALLS. `compose_route` and `add_widgets` are
        also tools in the ReAct catalogue, which is the path a live chat turn
        takes. Both arrive here; a private copy of the loading-and-committing
        would be a second answer to what composing a route means, and it would
        drift the first time either was touched.
        """
        from services.smith.compose import run as compose_run

        route = str(understanding.get("route") or "").strip()
        widgets = [str(w) for w in (understanding.get("widgets") or [])]
        # The composition runs for about a minute. Handing it the same sink
        # `understand_ask` used means the wait carries the model's reasoning
        # instead of a spinner — and it is the same sink, so a turn reads as
        # one continuous train of thought rather than two disconnected ones.
        out = compose_run(str(self.output_dir), verb, route=route,
                          widgets=widgets, request=user_message,
                          reasoning=self._reasoning)

        if not out.get("applied"):
            # A refusal is an outcome. Reporting it beats claiming success with
            # nothing behind it, which is the failure this path is a reaction to.
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or
                                         f"I could not {verb.replace('_', ' ')} "
                                         f"{route} and have changed nothing."))

        touched = list(out.get("edited_paths") or [])
        return TurnResult(
            status="resolved",
            answer=(str(out.get("diff_summary") or f"I updated {route}.")
                    + (f" Updated: {', '.join(touched[:6])}." if touched
                       else "")),
            touched_paths=touched,
        )

    def run_iteration(self, user_message: str,
                      history: list[tuple[str, str]] | None = None) -> TurnResult:
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

        # THE EXCHANGE, NOT JUST THE LATEST LINE. Smith asks "is that right?"
        # and the reply is the word "yes", which means nothing without the
        # question above it. Default None keeps every existing caller — and
        # every test — working unchanged.
        seam_kwargs: dict[str, Any] = {"history": history or []}
        if self._reasoning is not None:
            seam_kwargs["reasoning"] = self._reasoning
        try:
            understanding = self._understand(
                user_message, blueprint_ctx, **seam_kwargs,
            ) or {}
        except TypeError:
            # A seam that predates the history argument. Degrades to the old
            # single-turn behaviour rather than failing the turn.
            understanding = self._understand(user_message, blueprint_ctx) or {}

        # ANSWERED, SO NOTHING TO CHANGE. §8 gives Smith the Blueprint as a
        # memory layer and `pick_relevant_slice` has already put the relevant
        # part of it in front of the model. A question reaching here used to
        # come back as a request to restate it as a change, which sends the
        # user away to rephrase something Smith could already answer.
        #
        # `no_op` rather than a new status: the existing meaning — read,
        # nothing needed changing — is exactly what answering is, and it does
        # not hand off to the DAG, so a question no longer produces a run.
        answered = (understanding.get("answer") or "").strip()
        if answered:
            return TurnResult(status="no_op", answer=answered)

        clarification = (understanding.get("clarification_needed") or "").strip()
        if clarification:
            return TurnResult(status="asked", answer=clarification)

        # WHICH VERB, BEFORE WHICH FIELDS. Every request was held to a rename's
        # five required fields, so a composition could not be expressed at all.
        # Requirements are per verb now; see services/smith/verbs.
        from services.smith.verbs import (VERB_HELP, is_known, missing_fields,
                                          verb_of)

        verb = verb_of(understanding)
        if not is_known(understanding):
            return TurnResult(
                status="needs_user",
                answer=("I did not recognise that as something I can do. I can "
                        + "; ".join(f"{v} — {h.split('.')[0].lower()}"
                                    for v, h in VERB_HELP.items()) + "."),
            )
        # Only the new verbs are gated here. `rename` keeps the path it always
        # had — its fields are enforced by `understand_ask`, and re-checking
        # them in the turn made a call that used to reach the dispatcher stop
        # short of it.
        if verb != "rename":
            gaps = missing_fields(understanding)
            if gaps:
                return TurnResult(
                    status="asked",
                    answer=(f"I can do that, I just need {' and '.join(gaps)}. "
                            + VERB_HELP.get(verb, "")),
                )

        if verb == "connect_figma":
            return self._connect_figma(understanding)
        if verb == "connect_uxpilot":
            return self._connect_uxpilot(understanding)
        if verb in ("compose_route", "add_widgets"):
            return self._compose(verb, understanding, user_message)
        if verb == "rebuild":
            # A CHAT TURN CANNOT START A RUN, so it must not imply that it can.
            # The build is driven by the client — `useBlueprintRun` posts the
            # run request with `approved: true` — and this handler has no way
            # to reach it. It used to answer "say rebuild again to confirm",
            # and nothing consumed the confirmation: saying it again returned
            # the same sentence forever.
            return TurnResult(
                status="needs_user",
                answer=("Building the whole application is started from the "
                        "definition, not from chat: open the \u201cDefinition "
                        "ready to review\u201d card above and press "
                        "\u201cApprove and build\u201d. That runs the pages, "
                        "the data and the workflows, which takes a few "
                        "minutes.\n\nI can still change one screen from here "
                        "\u2014 name the route and I will rebuild that."),
            )

        target_file = (understanding.get("target_file") or "").strip()
        element_label = (understanding.get("element_label") or "").strip()
        if not target_file:
            return TurnResult(
                status="asked",
                answer="I need one more detail — which file or screen "
                       "should I edit? A route path or a screen name works.",
            )

        # The "is this even a rename?" question is the VERB's now, decided
        # above, so it is not re-litigated here. f1a601f checked `new_value`
        # at this point and stopped turns that carry the rename shape without
        # it — the dispatcher derives that field, and an injected mover does
        # not need it at all.
        move = self._move(understanding, self.output_dir)
        if move is None:
            return TurnResult(
                status="no_op",
                answer=(
                    f"I looked for \u201c{element_label}\u201d in "
                    f"{target_file} and could not find it, so I have changed "
                    "nothing rather than editing the nearest thing. If it is "
                    "there under different wording, tell me the exact text."
                ),
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
