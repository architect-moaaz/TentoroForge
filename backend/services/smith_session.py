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

from services.smith import pending_ask
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
    tree_changes,
    tree_diff_lines,
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
        #: The turn's whole ask — what was asked for, plus the answer to any
        #: question Smith asked about it. Set by `run_iteration`.
        self._ask = ""
        #: What was typed on THIS turn, before the carried ask is folded in.
        self._last_message = ""

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
                options=["Specification", "Reference"],
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

    def _connect_service(self, understanding: dict) -> "TurnResult":
        """Make the application talk to an outside service, or say why not.

        Outbound email is the one that is real: the owner names their service,
        the Blueprint records it with the NAMES of its variables, the
        projection writes the binding into the app, and the key itself is set
        once on the platform — never here, because this conversation is
        written to disk (§42). Anything with no adapter is the refusal shape:
        the reason, and the nearest thing that works, as chips.
        """
        from services.smith.email_connect import run as go

        said = str(understanding.get("integration") or "").strip()
        out = go(str(self.output_dir), service=said, reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason")
                                         or "I could not connect that and have changed nothing."),
                              options=list(out.get("options") or []))
        touched = list(out.get("edited_paths") or [])
        return TurnResult(status="resolved", answer=str(out.get("diff_summary") or "Done."),
                          touched_paths=touched,
                          diff_summary=", ".join(touched[:8]) if touched else "")

    def _disconnect_design(self, user_message: str) -> "TurnResult":
        """Remove the connected design and compose every screen from components.

        The inverse of :meth:`_connect_figma` and :meth:`_connect_uxpilot`.
        One Blueprint change through `design_disconnect`, then the composer
        over the pages that lost their frame — in this turn, the way
        `_compose` runs the composer, so the panel that asked sees it land.
        """
        from services.smith.design_disconnect import disconnect_and_recompose
        out = disconnect_and_recompose(str(self.output_dir), user_message,
                                       reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="no_op",
                              answer=str(out.get("reason") or "No design is connected."))
        sources = ", ".join(out.get("sources") or []) or "the design"
        failed = out.get("failed") or []
        answer = (f"Disconnected {sources}. {len(out.get('unbound') or [])} screen(s) no "
                  f"longer build from a frame; {len(out.get('completed') or [])} step(s) "
                  "re-ran to compose them from the component library.")
        if failed:
            answer += f" These did not finish: {', '.join(failed)}."
        return TurnResult(status="resolved", answer=answer,
                          diff_summary=f"version {out.get('version')}: design disconnected, "
                                       f"{out.get('dropped_layouts', 0)} drawn layout(s) retired")

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
                options=["Specification", "Reference"],
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

    def _stale_plan_reason(self) -> str:
        """Why the plan approval no longer stands, or "" when it does (or there
        is no Blueprint / no approval yet to be stale)."""
        from pathlib import Path
        if not (Path(self.output_dir) / ".forge" / "blueprint" / "current.json").exists():
            return ""
        try:
            from services.blueprint import approval
            from services.blueprint.service import BlueprintService
            doc = BlueprintService.load(output_dir=str(self.output_dir)).doc
            if approval.state_of(doc, "plan") != "stale":
                return ""
            answer = approval.latest(doc, "plan") or {}
            return (f"the plan was approved at version {answer.get('version', '?')} and the definition "
                    f"is now at version {doc.get('version', '?')} — it has changed since and must be "
                    "reviewed again")
        except Exception:  # noqa: BLE001 — a gate that cannot be read does not block the answer
            logger.exception("could not read the plan gate")
            return ""

    def _definition(self, verb: str, understanding: dict, user_message: str) -> "TurnResult":
        """Fields, requirements, product, APIs and integrations — the rest of
        the definition, changeable after the build."""
        u = {k: understanding.get(k) for k in ("entity", "field", "new_value", "requirement", "change", "api", "integration")}
        field = u.get("field")
        field = str(field.get("name") or "") if isinstance(field, dict) else str(field or "")
        text = {"add_requirement": u.get("requirement"), "edit_requirement": u.get("requirement"),
                "remove_requirement": u.get("requirement"), "add_api": u.get("api"), "remove_api": u.get("api"),
                "add_integration": u.get("integration"), "remove_integration": u.get("integration"),
                "edit_product": u.get("change")}.get(verb)
        if verb in ("rename_field", "remove_field"):
            from services.smith.field_change import run as go
            out = go(str(self.output_dir), verb, entity=str(u.get("entity") or ""), field=field,
                     new_value=str(u.get("new_value") or ""), reasoning=self._reasoning)
        else:
            from services.smith.definition_change import run as go
            out = go(str(self.output_dir), verb, text=str(text or "").strip() or user_message.strip(),
                     change=str(u.get("change") or "").strip(), reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or f"I could not {verb.replace('_', ' ')} and have changed nothing."))
        touched = list(out.get("edited_paths") or [])
        return TurnResult(status="resolved", answer=str(out.get("diff_summary") or "Done."),
                          touched_paths=touched, diff_summary=", ".join(touched[:8]) if touched else "")

    def _section(self, verb: str, understanding: dict, user_message: str) -> "TurnResult":
        """Access, rules and entities — three Blueprint sections, one dispatch.
        Each seam is also a tool; both reach the same `run`."""
        u = {k: str(understanding.get(k) or "").strip() for k in ("change", "rule", "entity")}
        reasoning = self._reasoning
        if verb == "edit_access":
            from services.smith.access_change import run as go
            out = go(str(self.output_dir), u["change"] or user_message.strip(), reasoning=reasoning)
        elif verb in ("add_rule", "edit_rule", "remove_rule"):
            from services.smith.rule_change import run as go
            out = go(str(self.output_dir), verb, rule=u["rule"] or user_message.strip(), change=u["change"], reasoning=reasoning)
        else:
            from services.smith.entity_change import run as go
            # add_field's `entity` is a name; here it is the ask in the user's words.
            ref = u["entity"] or user_message.strip()
            if verb == "remove_entity":
                gate = self._confirm_cascade("remove_entity", ref, self._cascade_of_entity(ref))
                if gate is not None:
                    return gate
            out = go(str(self.output_dir), verb, entity=ref, reasoning=reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or f"I could not {verb.replace('_', ' ')} and have changed nothing."))
        touched = list(out.get("edited_paths") or [])
        return TurnResult(status="resolved", answer=str(out.get("diff_summary") or "Done."),
                          touched_paths=touched, diff_summary=", ".join(touched[:8]) if touched else "")

    def _cascade_of_entity(self, ref: str) -> list[str]:
        """What retiring this record would take with it, in a person's words."""
        from services.smith.engine_blueprint_adapter import load_engine_doc
        from services.smith.entity_change import consequences

        said = consequences(load_engine_doc(str(self.output_dir)) or {}, ref)
        if not said.get("found"):
            return []
        out = []
        if said["pages"]:
            out.append(f"{len(said['pages'])} screen(s) — {', '.join(said['pages'])} — "
                       "retired and taken off the menu")
        if said["workflows"]:
            out.append(f"{len(said['workflows'])} automatic process(es) — "
                       f"{', '.join(said['workflows'])} — stopped, and their "
                       "buttons taken off every screen")
        if said["pointing"]:
            out.append("records that point at it: " + ", ".join(said["pointing"]))
        return out

    def _cascade_of_page(self, route: str) -> list[str]:
        """What else changes when a screen goes, in a person's words."""
        from services.smith.engine_blueprint_adapter import load_engine_doc
        from services.smith.page_change import consequences

        said = consequences(load_engine_doc(str(self.output_dir)) or {}, route)
        if not said.get("found"):
            return []
        out = []
        if said["menu"]:
            out.append("it comes off the menu (" + ", ".join(said["menu"]) + ")")
        if said["links"]:
            out.append(f"{len(said['links'])} link(s) to it come off other screens: "
                       + ", ".join(said["links"][:6]))
        if said["landing"]:
            out.append("the application stops opening on it, and opens on whatever "
                       "the menu leads with instead")
        if said["launches"]:
            out.append("processes started from it lose the screen they start from: "
                       + ", ".join(said["launches"]))
        if said["widgets"]:
            out.append(f"{said['widgets']} widget(s) on it are retired with it")
        return out

    def _remove_page(self, route: str) -> "TurnResult":
        """Take a whole screen out — `services.smith.page_change.run`."""
        from services.smith.engine_blueprint_adapter import load_engine_doc
        from services.smith.page_change import run as remove_run
        from services.smith.page_change import why_not

        # THE REFUSAL COMES BEFORE THE QUESTION. There is one screen that
        # cannot go — the last one anyone can arrive at — and asking "shall I
        # go ahead?" about it, only to answer "I cannot" to the yes, is a
        # worse turn than the refusal on its own.
        why = why_not(load_engine_doc(str(self.output_dir)) or {}, route)
        if why:
            return TurnResult(status="needs_user", answer=why)
        # A SCREEN IS NOT A LEAF. The menu names it, other screens link to it,
        # the application may open on it — so what the removal takes is named
        # before it is taken, exactly as a field's and an entity's are. A
        # screen nothing points at goes without a question.
        gate = self._confirm_cascade("remove_page", route, self._cascade_of_page(route))
        if gate is not None:
            return gate
        out = remove_run(str(self.output_dir), route=route, reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or
                                         "I could not remove that screen and have changed nothing."))
        touched = list(out.get("edited_paths") or [])
        return TurnResult(status="resolved", answer=str(out.get("diff_summary") or "Removed the screen."),
                          touched_paths=touched,
                          diff_summary=", ".join(touched[:8]) if touched else "")

    def _cascade_of_field(self, entity: str, field: str) -> list[str]:
        """Where a box is used, and the one thing undo cannot bring back."""
        from services.smith.engine_blueprint_adapter import load_engine_doc
        from services.smith.field_change import consequences

        said = consequences(load_engine_doc(str(self.output_dir)) or {}, entity, field)
        if not said.get("found"):
            return []
        out = ["everything written in it so far, which cannot be brought back"]
        if said["used"]:
            out.append("it comes off " + ", ".join(said["used"]))
        if said["rules"]:
            out.append("rules that check it are retired: " + ", ".join(said["rules"]))
        if said["workflows"]:
            out.append("processes that use it are re-authored: " + ", ".join(said["workflows"]))
        return out

    def _confirm_cascade(self, verb: str, target: str, consequences: list[str]) -> "TurnResult | None":
        """Show what a change takes with it and wait for a yes — or None when
        the yes is already in hand.

        The dependency set was computed one line before the removal started,
        and nobody was shown it. The yes is kept against a fingerprint of THIS
        operation (services.smith.confirm), so the turn that says "go ahead"
        is not read as the same ask arriving again — which would show the
        question a second time, for ever.
        """
        from services.smith import confirm

        if not consequences:
            return None                       # nothing cascades: nothing to warn about
        if confirm.granted(self.output_dir, self._last_message, verb, target):
            return None
        confirm.remember(self.output_dir, confirm.fingerprint(verb, target))
        return TurnResult(
            status="asked",
            answer=("That does not only remove what you named. It also takes:\n"
                    + "\n".join(f"- {c}" for c in consequences)
                    + "\n\nShall I go ahead?"),
            options=[confirm.YES_LABEL, confirm.NO_LABEL],
        )

    def _navigation(self, understanding: dict, user_message: str) -> "TurnResult":
        """Change the menu — the `navigation` section. One implementation in
        `services.smith.navigation_change.run`, shared with the tool."""
        from services.smith.navigation_change import run as nav_run

        change = str(understanding.get("change") or "").strip() or user_message.strip()
        out = nav_run(str(self.output_dir), change, reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or "I could not change the menu and have changed nothing."))
        touched = list(out.get("edited_paths") or [])
        return TurnResult(status="resolved", answer=str(out.get("diff_summary") or "Changed the menu."),
                          touched_paths=touched, diff_summary=", ".join(touched) if touched else "")

    def _workflow(self, verb: str, understanding: dict, user_message: str) -> "TurnResult":
        """Add, change or retire a business process — the `workflows` section,
        which no other verb touched. One implementation in
        `services.smith.workflow_change.run`, shared with the tools."""
        from services.smith.workflow_change import run as workflow_run

        out = workflow_run(str(self.output_dir), verb,
                           workflow=str(understanding.get("workflow") or "").strip() or user_message.strip(),
                           change=str(understanding.get("change") or "").strip(),
                           route=str(understanding.get("route") or "").strip(),
                           reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or
                                         f"I could not {verb.replace('_', ' ')} and have changed nothing."))
        touched = list(out.get("edited_paths") or [])
        return TurnResult(status="resolved", answer=str(out.get("diff_summary") or "Done."),
                          touched_paths=touched,
                          diff_summary=", ".join(touched[:8]) if touched else "")

    def _restyle(self, understanding: dict, user_message: str) -> "TurnResult":
        """Change the look of the application — the design system, which no
        other verb touches. Same shape as `_compose`: one implementation in
        `services.smith.restyle.run`, shared with the tool of the same name."""
        from services.smith.restyle import run as restyle_run

        change = str(understanding.get("change") or "").strip() or user_message.strip()
        out = restyle_run(str(self.output_dir), change, reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or
                                         "I could not restyle the application and have changed nothing."))
        touched = list(out.get("edited_paths") or [])
        return TurnResult(status="resolved", answer=str(out.get("diff_summary") or "Restyled."),
                          touched_paths=touched,
                          diff_summary=", ".join(touched) if touched else "")

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
        missing = [str(m) for m in (out.get("missing") or [])]
        if missing:
            # THE SCREEN CHANGED, THE ASK IS NOT ON IT. The composer was told
            # what to add and laid the page out without it; "added X to
            # /route" here would be the claim that sent the person to look
            # for a field that is not there.
            return TurnResult(
                status="needs_user",
                answer=("I re-composed **" + route + "**, but the new screen does "
                        "not show what you asked for:\n"
                        + "\n".join(f"- {m}" for m in missing)
                        + "\n\nIf it is a field of the record, ask me to add "
                          "the field to the entity and I will put it on the "
                          "form directly. Otherwise say what it should contain "
                          "and I will compose the screen again."),
                touched_paths=touched,
            )
        # A paragraph of its own: the summary may end in a list, and a
        # sentence appended to a list's last line becomes part of the bullet.
        return TurnResult(
            status="resolved",
            answer=(str(out.get("diff_summary") or f"I updated {route}.")
                    + (f"\n\nUpdated: {', '.join(touched[:6])}." if touched
                       else "")),
            touched_paths=touched,
        )

    @staticmethod
    def _on_route(entry: dict, target: str) -> bool:
        """Whether a collected label sits on the screen `target` names."""
        from services.smith.labels import normalise
        want = normalise(target)
        return bool(want) and want in (normalise(entry.get("route") or ""),
                                       normalise(entry.get("page") or ""))

    def _run_step(self, step: str) -> "TurnResult":
        """One step of an agreed plan, as an ordinary turn.

        Re-entering `_iterate` rather than a second execution path: a step is
        a normal ask and must be able to do everything one can — ask its own
        question, refuse, confirm a cascade — with the rest of the plan still
        waiting behind it.
        """
        self._ask = step
        self._last_message = step
        return self._iterate(step, None)

    def _revert(self) -> "TurnResult":
        """Undo the last change (§91/§93).

        The one verb that needs no facts from the ask: it is always the most
        recent change, and asking which one would be asking the person to know
        what Smith recorded.
        """
        from services.smith.revert import run as revert_run

        out = revert_run(str(self.output_dir), reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or "I could not undo that."))
        return TurnResult(status="resolved",
                          answer=str(out.get("diff_summary") or "Undone."),
                          touched_paths=list(out.get("edited_paths") or []))

    def _guide(self) -> "TurnResult":
        """The guide the owner hands their staff (§06).

        The one verb that reads the application and writes nothing back to it:
        no change is recorded, no projection re-runs, and `touched_paths`
        carries the guide file alone. It needs no facts from the ask because
        the audiences and the screens are in the document — asking who it is
        for would be asking the owner to list their own roles.
        """
        from services.smith.handover import run as guide_run, summary_of

        out = guide_run(str(self.output_dir),
                        app_root=str(Path(self.output_dir) / "app"),
                        reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or "I could not write the guide."))
        return TurnResult(status="resolved",
                          answer=summary_of(out),
                          touched_paths=list(out.get("edited_paths") or []))

    def _spend(self) -> "TurnResult":
        """What this application has cost to run.

        Answers, changes nothing, and touches no path — so it resolves even
        when there is no figure to give: "I cannot see what it cost" is a
        complete answer, and the only alternative is a zero that reads like a
        statement of account.
        """
        from services.smith.spend import run as spend_run

        out = spend_run(str(self.output_dir), reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason")
                                         or "I could not read what this has cost."))
        return TurnResult(status="resolved",
                          answer=str(out.get("diff_summary") or ""),
                          touched_paths=[])
    def _import_data(self, understanding: dict) -> "TurnResult":
        """Load the spreadsheet they attached into one kind of record.

        Two turns, and the first one writes NOTHING: it says how many rows
        would land, how many would not and why, and which column becomes
        which field. An import is the one change whose subject is data the
        owner cannot regenerate, and finding out what it did by looking at
        the result is not good enough.
        """
        from services.smith.data_import import run as import_run

        entity = str(understanding.get("entity") or "").strip()
        out = import_run(str(self.output_dir), entity,
                         message=self._last_message, reasoning=self._reasoning)
        if out.get("asked"):
            return TurnResult(status="asked", answer=str(out.get("reason") or ""),
                              options=list(out.get("options") or []))
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or
                                         "I could not load that and nothing has been written."))
        return TurnResult(status="resolved",
                          answer=str(out.get("diff_summary") or "Loaded."),
                          touched_paths=list(out.get("edited_paths") or []))

    def _export_data(self, understanding: dict) -> "TurnResult":
        """Hand them their records back as a spreadsheet.

        The one change verb that changes nothing — so `no_op` rather than
        `resolved`: nothing was touched, and a turn that reports a change it
        did not make is the thing every other seam here is careful about.
        The project id is passed because the link the answer carries is a
        platform URL, and the session is the only caller that knows it.
        """
        from services.smith.data_export import run as export_run

        out = export_run(str(self.output_dir),
                         str(understanding.get("entity") or "").strip(),
                         project_id=str(self.project_id or ""),
                         reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason") or
                                         "I could not produce that file."))
        return TurnResult(status="no_op",
                          answer=str(out.get("diff_summary") or "Exported."))

    def _accounts(self, verb: str, understanding: dict) -> "TurnResult":
        """Add, remove or reset ONE PERSON'S login.

        Not a Blueprint change and not a role change: `edit_access` decides
        what a Ward Manager may do, and this decides whether Dave exists and
        can get in. The roster is a project ledger, so an undo of an unrelated
        change cannot silently re-admit someone who was removed. See
        `services.smith.accounts`.
        """
        from services.smith.accounts import run as accounts_run

        out = accounts_run(
            str(self.output_dir), verb,
            email=str(understanding.get("email") or "").strip(),
            person=str(understanding.get("person") or "").strip(),
            name=str(understanding.get("person_name") or "").strip(),
            role=str(understanding.get("role") or "").strip(),
            reasoning=self._reasoning)
        if not out.get("applied"):
            return TurnResult(status="needs_user",
                              answer=str(out.get("reason")
                                         or "I could not change that login, and have "
                                            "changed nothing."))
        touched = list(out.get("edited_paths") or [])
        return TurnResult(status="resolved", answer=str(out.get("diff_summary") or "Done."),
                          touched_paths=touched,
                          diff_summary=", ".join(touched[:8]) if touched else "")
    def _explain_incident(self, verb: str) -> "TurnResult":
        """Answer "it crashed" / "it's really slow" from what the app reported.

        THE ONLY TWO VERBS WHOSE ANSWER COMES FROM THE RUNNING APPLICATION
        rather than from the document. Both change nothing — they read the
        project's incident ledger — so the result is `needs_user`: there is an
        account, and where a crash names a control or a workflow there is a
        repair to click, which is a decision only the owner can make.
        """
        from services.incident_ledger import KIND_CRASH, KIND_SLOW
        from services.smith.incidents import run as incidents_run

        out = incidents_run(str(self.output_dir),
                            kind=KIND_SLOW if verb == "explain_slowness" else KIND_CRASH)
        return TurnResult(status="needs_user", answer=str(out.get("answer") or ""),
                          options=list(out.get("options") or []))

    def _add_field(self, understanding: dict) -> "TurnResult":
        """Add one column to an existing entity — the incremental data-model
        change a field-add is (F-01). The field is added to the Living
        Blueprint's entity and the data layer is re-projected, so the new column
        appears in ``src/db/schema/<entity>.ts`` and reaches the app as a
        non-destructive ``drizzle-kit push`` — existing rows keep their data and
        nothing rebuilds. Displaying the field is a separate later edit_page
        turn. Falls back to the file-based seam for a registry-only app.
        """
        entity = str(understanding.get("entity") or "").strip()
        field = understanding.get("field") if isinstance(understanding.get("field"), dict) else {}
        fname = str(field.get("name") or "").strip()
        if not entity or not fname:
            return TurnResult(status="asked",
                              answer="Which record should it go on, and what should the box be called?")

        # Map Smith's SQL-ish type words to the Blueprint's field vocabulary.
        _t = str(field.get("type") or "string").lower().strip()
        bp_type = ({"text": "string", "varchar": "string", "str": "string",
                    "int": "integer", "integer": "integer", "number": "integer",
                    "decimal": "decimal", "numeric": "decimal", "float": "decimal",
                    "money": "decimal", "bool": "boolean", "boolean": "boolean",
                    "date": "date", "datetime": "timestamp",
                    "timestamp": "timestamp"}.get(_t, _t)) or "string"

        from pathlib import Path
        bp_path = Path(self.output_dir) / ".forge" / "blueprint" / "current.json"
        if not bp_path.exists():
            # Registry-only (older) app — the file-based seam is the right tool.
            from services.fix_applier import _apply_add_field
            out = _apply_add_field(
                str(self.output_dir),
                {"proposedFix": {"seam": "add_field",
                                 "patch": {"entity": entity, "field": field}}}, git=False)
            if not out.get("applied"):
                return TurnResult(status="needs_user",
                                  answer=str(out.get("reason") or
                                             f"I could not add {fname!r} to {entity}."))
            touched = [c["path"] for c in (out.get("changes") or []) if c.get("path")]
            return self._added_field_result(fname, bp_type, entity, touched)

        # THE COLUMN AND THE CONTROL, IN ONE TURN. "Add father's name in the
        # Nurse Registration" asks for a place to type it, not only a column;
        # the seam puts the field on every form that edits the entity and
        # every table that lists it, commits the Blueprint, and re-projects.
        try:
            from services.blueprint.service import BlueprintService
            from services.smith import field_change as fc
            from services.smith.section_change import SectionChangeError
            svc = BlueprintService.load(output_dir=str(self.output_dir))
            app_root = Path(self.output_dir) / "app"
            if not (app_root / "src").exists():
                app_root = Path(self.output_dir)
            try:
                out = fc.add_field(
                    svc, entity,
                    {"name": fname, "type": bp_type,
                     "label": str(field.get("label") or "")},
                    app_root=str(app_root), reasoning=self._reasoning)
            except SectionChangeError as exc:
                return TurnResult(status="needs_user", answer=str(exc))
        except Exception as exc:  # noqa: BLE001 — a turn degrades, it does not crash
            logger.exception("add_field failed for %s.%s", entity, fname)
            return TurnResult(status="needs_user",
                              answer=f"I could not add {fname!r} to {entity}: {exc}")
        return TurnResult(status="resolved", answer=fc.summary_of("add_field", out),
                          touched_paths=list(out.get("edited_paths") or []))

    @staticmethod
    def _added_field_result(fname: str, ftype: str, entity: str,
                            touched: list[str]) -> "TurnResult":
        return TurnResult(
            status="resolved",
            answer=(f"Added **{fname}** to **{entity}** — a {ftype} box, optional, "
                    "so records that already exist simply have it empty and "
                    "nothing is rebuilt"
                    + (f". Updated: {', '.join(touched[:6])}." if touched else ".")
                    + " Say which screen should show it and I will put it there."),
            touched_paths=touched,
        )

    def run_iteration(self, user_message: str,
                      history: list[tuple[str, str]] | None = None) -> TurnResult:
        """One turn, carrying whatever ask the last turn could not act on.

        A change is often two turns: the ask, Smith's question about it, and
        the answer. The turn that acts is the third, and it used to act on the
        answer alone — "a new page at /calculator" became a page's whole
        purpose and the composer's only subject, and the sentence that asked
        for a calculator reached nothing. `services.smith.pending_ask` holds
        the ask between the two, recorded when Smith asks and taken here; the
        seams get both, in the order they were said.
        """
        from services.smith import plan as _plan_mod

        # AGREED, SO DO THE FIRST ONE NOW. The yes is a turn of its own; it
        # would otherwise be spent saying "starting" and the person would have
        # to ask again for the thing they just agreed to.
        if _plan_mod.peek(self.output_dir) and (
                _plan_mod.wants_next(user_message)
                or user_message.strip() == _plan_mod.ALL_LABEL
                or user_message.strip() == _plan_mod.FIRST_LABEL):
            only_one = user_message.strip() == _plan_mod.FIRST_LABEL
            step = _plan_mod.take_next(self.output_dir)
            if only_one:
                _plan_mod.clear(self.output_dir)
            if step:
                pending_ask.clear(self.output_dir)
                result = self._run_step(step)
                rest = _plan_mod.peek(self.output_dir)
                note = _plan_mod.remaining_note(rest)
                if note and result.status == "resolved":
                    result.answer += note
                return result
        # AGREED, SO LOAD THEM NOW. The dry run described an import and is
        # holding it; the yes is a turn of its own and the model would have to
        # re-derive the verb from the question above it to get here. It is
        # applied under the mapping that was SHOWN — see
        # `services.smith.data_import.agreed`, which takes the plan as it
        # reads it, so a yes cannot apply twice and cannot apply something else.
        from services.smith import data_import as _import_mod
        if _import_mod.wants(_import_mod.peek(self.output_dir), user_message):
            pending_ask.clear(self.output_dir)
            self._last_message = user_message
            from services.smith.data_import import run as _import_run
            out = _import_run(str(self.output_dir), message=user_message,
                              reasoning=self._reasoning)
            if not out.get("applied"):
                return TurnResult(status="needs_user",
                                  answer=str(out.get("reason") or
                                             "I could not load that and nothing has been written."))
            return TurnResult(status="resolved",
                              answer=str(out.get("diff_summary") or "Loaded."),
                              touched_paths=list(out.get("edited_paths") or []))
        if user_message.strip() == _plan_mod.REWORD_LABEL:
            _plan_mod.clear(self.output_dir)
            return TurnResult(status="asked",
                              answer="Go ahead — tell me the one thing you want first.")

        carried = pending_ask.take(self.output_dir)
        self._ask = pending_ask.joined(carried, user_message)
        # The consent test reads what was typed NOW, not the accumulated ask:
        # "go ahead" is a yes, "remove complaints\n\ngo ahead" is not a
        # sentence anybody typed.
        self._last_message = user_message
        result = self._iterate(user_message, history)
        if result.status == "asked":
            # Still unanswered: keep it for the turn that answers. The
            # question itself is not kept — it is Smith's, not the ask.
            pending_ask.remember(self.output_dir, self._ask)
        return result

    def _iterate(self, user_message: str,
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

        # SEVERAL ASKS IN ONE MESSAGE. Shown as a plan and agreed to once,
        # rather than the biggest one happening in silence. Nothing is done
        # before the yes — starting on step one while showing the list is the
        # old behaviour with a receipt.
        from services.smith import plan as _plan
        steps = [str(a).strip() for a in (understanding.get("asks") or []) if str(a).strip()]
        if len(steps) > 1 and not _plan.wants_next(user_message):
            from services.smith import confirm as _confirm
            if not _confirm.granted(self.output_dir, self._last_message, "plan", " | ".join(steps)):
                _confirm.remember(self.output_dir, _confirm.fingerprint("plan", " | ".join(steps)))
                planned, over = _plan.split(steps)
                _plan.remember(self.output_dir, planned)
                return TurnResult(status="asked",
                                  answer=_plan.as_question(planned, over),
                                  options=[_plan.ALL_LABEL, _plan.FIRST_LABEL,
                                           _plan.REWORD_LABEL])

        clarification = (understanding.get("clarification_needed") or "").strip()
        if clarification:
            # The choices ride as chips: picking one sends its label as the
            # next turn, the way the definition's questions are answered.
            choices = [str(c).strip() for c in (understanding.get("clarification_options") or [])
                       if str(c or "").strip()]
            return TurnResult(status="asked", answer=clarification, options=choices)

        # WHICH VERB, BEFORE WHICH FIELDS. Every request was held to a rename's
        # five required fields, so a composition could not be expressed at all.
        # Requirements are per verb now; see services/smith/verbs.
        from services.smith.verbs import (is_known, missing_fields,
                                          verb_of)

        verb = verb_of(understanding)
        if not is_known(understanding):
            # THREE TO CHOOSE FROM, NOT THIRTY TO READ. The whole capability
            # list is the right answer to "what can you do?" and the wrong one
            # to a misrouted ask: it is a wall with nothing to click. The
            # closest few, as the sentences that reach them, are a question.
            from services.smith.capabilities import nearest as _nearest
            close = _nearest(user_message)
            if close:
                return TurnResult(
                    status="needs_user",
                    answer=("I did not recognise that as something I can do. "
                            "Did you mean one of these?"),
                    options=[example for _verb, example in close] + ["Something else"],
                )
            from services.smith.capabilities import summary as _capabilities
            return TurnResult(
                status="needs_user",
                answer=("I did not recognise that as something I can do, and it "
                        "is not close to anything I know.\n\n" + _capabilities()),
            )
        # Only the new verbs are gated here. `rename` keeps the path it always
        # had — its fields are enforced by `understand_ask`, and re-checking
        # them in the turn made a call that used to reach the dispatcher stop
        # short of it.
        if verb != "rename":
            gaps = missing_fields(understanding)
            if gaps:
                # THE ANSWER SET IS IN THE BLUEPRINT. "I just need entity and
                # field" named two contract slots and left the person to guess
                # Smith's spelling of a value the document already holds. Asked
                # with its own answers attached, the question is a click.
                from services.smith.engine_blueprint_adapter import load_engine_doc
                from services.smith.slot_options import ask_for, fill_from
                doc = load_engine_doc(str(self.output_dir)) or {}
                # ASKED FOR ONLY WHAT WAS NOT SAID. The answer is often in the
                # message already — "delete the Master Data page" names the
                # screen — and asking for it is asking a person to repeat
                # themselves.
                known = fill_from(gaps, self._ask, doc, understanding)
                if known:
                    understanding = {**understanding, **known}
                    gaps = missing_fields(understanding)
                if gaps:
                    question, choices = ask_for(gaps, doc, understanding)
                    return TurnResult(status="asked", answer=question, options=choices)

        if verb == "restyle":
            return self._restyle(understanding, self._ask)
        if verb in ("add_workflow", "edit_workflow", "remove_workflow"):
            return self._workflow(verb, understanding, self._ask)
        if verb == "edit_navigation":
            return self._navigation(understanding, self._ask)
        if verb in ("edit_access", "add_rule", "edit_rule", "remove_rule", "add_entity", "remove_entity"):
            return self._section(verb, understanding, self._ask)
        if verb == "remove_field":
            # A COLUMN'S DATA IS THE ONE THING UNDO DOES NOT BRING BACK, so it
            # is named before it goes, with everywhere the box is used.
            gate = self._confirm_cascade(
                "remove_field",
                f"{understanding.get('entity') or ''}.{(understanding.get('field') or {}).get('name') or ''}",
                self._cascade_of_field(
                    str(understanding.get("entity") or ""),
                    str((understanding.get("field") or {}).get("name") or "")))
            if gate is not None:
                return gate
        if verb in ("rename_field", "remove_field", "add_requirement", "edit_requirement", "remove_requirement",
                    "edit_product", "add_api", "remove_api", "add_integration", "remove_integration"):
            return self._definition(verb, understanding, self._ask)
        if verb == "connect_service":
            return self._connect_service(understanding)
        if verb == "connect_figma":
            return self._connect_figma(understanding)
        if verb == "connect_uxpilot":
            return self._connect_uxpilot(understanding)
        if verb == "disconnect_design":
            return self._disconnect_design(user_message)
        if verb in ("compose_route", "add_widgets"):
            return self._compose(verb, understanding, self._ask)
        if verb == "remove_page":
            return self._remove_page(str(understanding.get("route") or "").strip())
        if verb == "add_field":
            return self._add_field(understanding)
        if verb == "revert":
            return self._revert()
        if verb == "write_guide":
            return self._guide()
        if verb == "spend":
            return self._spend()
        if verb == "import_data":
            return self._import_data(understanding)
        if verb == "export_data":
            return self._export_data(understanding)
        if verb in ("add_login", "remove_login", "reset_login"):
            return self._accounts(verb, understanding)
        if verb in ("explain_crash", "explain_slowness"):
            return self._explain_incident(verb)
        from services.smith.limits import cannot as _cannot
        if _cannot(verb):
            # HONEST, AND NOT A DEAD END. These are the asks Smith genuinely
            # cannot serve; each now says why in a clause and offers the
            # nearest thing that works, as sentences a click can say.
            from services.smith.engine_blueprint_adapter import load_engine_doc
            from services.smith.limits import answer as _limit_answer
            said, options = _limit_answer(verb, understanding,
                                          load_engine_doc(str(self.output_dir)) or {})
            if said:
                return TurnResult(status="needs_user", answer=said, options=options)
        if verb == "rebuild":
            # A CHAT TURN CANNOT START A RUN, so it must not imply that it can.
            # The build is driven by the client — `useBlueprintRun` posts the
            # run request with `approved: true` — and this handler has no way
            # to reach it. It used to answer "say rebuild again to confirm",
            # and nothing consumed the confirmation: saying it again returned
            # the same sentence forever.
            # THE GATE IS CONSULTED HERE, before anyone spends anything. The
            # approval recorded at the last build is fingerprinted against the
            # product surface; a definition changed since is a stale approval,
            # and a build on a stale approval is refused with the reason and
            # the way to renew it — the card, whose "Approve and build" IS the
            # renewal. Nothing here starts a run.
            stale = self._stale_plan_reason()
            if stale:
                return TurnResult(
                    status="needs_user",
                    answer=(f"Not building on the current approval: {stale}. Open the "
                            "\u201cDefinition ready to review\u201d card above and press "
                            "\u201cApprove and build\u201d to renew it against the definition "
                            "as it now stands; the build then proceeds."),
                )
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

        if verb == "remove":
            # The move reads an empty `new_value` as "take it off" — the one
            # thing that separates a removal from a rename to it.
            understanding = {**understanding, "new_value": ""}

        target_file = (understanding.get("target_file") or "").strip()
        element_label = (understanding.get("element_label") or "").strip()

        from services.smith.engine_blueprint_adapter import load_engine_doc
        doc = load_engine_doc(str(self.output_dir)) or {}

        if not target_file:
            # The screens are in the Blueprint; asking for one by name and
            # leaving the person to type it is a question they answer worse
            # than a click does.
            from services.smith.slot_options import options_for
            return TurnResult(
                status="asked",
                answer="Which screen?",
                options=options_for("route", doc),
            )

        # THE TREE KNOWS THE WORDS; THE PERSON SHOULD NOT HAVE TO. The move
        # matches a label by string equality, so "the delete thing" and
        # "Delete  button" both reached "I looked for it and could not find
        # it" with a Delete sitting in the tree. Resolved here: one match is
        # used, several are asked about, none is still said plainly.
        if element_label:
            from services.smith.labels import collect, describe, resolve
            found = resolve(doc, element_label, target_file)
            if found.get("candidates"):
                return TurnResult(
                    status="asked",
                    answer=(f"There is more than one “{element_label}”. "
                            "Which one did you mean?"),
                    options=[describe(c) for c in found["candidates"]][:5],
                )
            if found.get("text"):
                if found["text"] != element_label:
                    understanding = {**understanding, "element_label": found["text"]}
                    element_label = found["text"]
            else:
                on_screen = [c["text"] for c in collect(doc)
                             if self._on_route(c, target_file)][:5]
                if on_screen:
                    return TurnResult(
                        status="asked",
                        answer=(f"I could not find “{element_label}” on "
                                f"{target_file}, so I have changed nothing. "
                                "Is it one of these?"),
                        options=on_screen,
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

        # Ground truth: what did the working tree actually see change?
        modified_now = set(git_status_modified(self.output_dir))
        # Baseline may have had uncommitted changes; only NEW ones this
        # turn count as Smith's.
        baseline_status = set(baseline.get("status") or [])
        # A generated project's repo has no commits, so to git all of
        # `app/` is one untracked entry before and after — a rewritten page
        # schema is invisible to it. The tree fingerprint sees the rewrite.
        baseline_tree = baseline.get("tree") or {}
        actually_touched = sorted((modified_now - baseline_status)
                                  | set(tree_changes(self.output_dir, baseline_tree)))

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

        # Diff-based checks — git's diff for what it tracks, the tree's for
        # what it cannot yet see.
        diff = (git_diff_lines(self.output_dir, actually_touched)
                + tree_diff_lines(self.output_dir, baseline_tree, actually_touched))

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

        # WHAT CHANGED, IN THE WORDS ON THE SCREEN. "Changed /master-data —
        # previous state → requested change" is the shape of a sentence with
        # nothing in it: it is what the template says when the model filled in
        # neither behaviour, which is most of the time for a rename or a
        # removal, where the label IS the change.
        label = str(understanding.get("element_label") or "").strip()
        new_text = str(understanding.get("new_value") or "").strip()
        if label and new_text:
            answer = f"Done — **{label}** on {target_file} now says **{new_text}**."
        elif label:
            answer = (f"Done — **{label}** is off {target_file}, and the screen "
                      "no longer offers what it did.")
        else:
            was = str(understanding.get("current_behavior") or "").strip()
            now = str(understanding.get("desired_behavior") or "").strip()
            answer = (f"Done — {target_file}: {was} → {now}." if was and now
                      else f"Done — {target_file} has been changed.")
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
