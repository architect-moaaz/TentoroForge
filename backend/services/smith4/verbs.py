"""The verbs, carried out — a table, not a chain.

`smith_session._perform` was an if-chain of forty branches, each calling one
`services.smith.<seam>.run` and re-reading its envelope into a TurnResult.
This is the same forty, as a table the loop dispatches through by name. The
seams are untouched: `restyle.run`, `workflow_change.run`, `field_change.run`
and the rest are the platform, and a v4 that rewrote them would be a v4 that
threw away the tests and the UAT history behind each.

WHAT A VERB NEEDS IS WHAT IT DECLARES. `REQUIRED_BY_VERB` is the contract;
`missing_fields` holds a call to it before this table is reached, and
`slot_options.fill_from` tries the message and the document first, so a screen
the person named is not asked for again. A verb in `REQUIRED_BY_VERB` with no
entry here fails `test_every_verb_is_performed`, which is the honest way for a
new verb to meet the loop.

THREE OF THE FOUR HONEST REFUSALS ARE CLOSED. `rename_entity`,
`change_field_type` and `edit_api` go through `write_section` — the loop's
primitive that briefs the agent owning a section — and their outcome is the
section's, refusal and all. `reorder` on a layout page still answers with
`limits.answer` (the tree edit has no reorder), and on a coded page composes.
Nothing here is a GATE in front of the loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from services.ground_truth import (
    git_diff_lines,
    git_status_modified,
    guard_delta,
    snapshot_baseline,
    tree_changes,
    tree_diff_lines,
)
from services.smith4.outcome import Outcome, from_seam

logger = logging.getLogger(__name__)


@dataclass
class Ctx:
    """What every verb may need and no verb should load for itself."""
    output_dir: str
    project_id: str
    #: What was typed on THIS turn — the consent tests read this.
    message: str
    #: The whole ask: the carried ask plus the message.
    ask: str
    reasoning: Any = None
    #: (output_dir) -> guard findings; injected so tests never run guards.
    guards: Callable[[str], list[dict]] = lambda _out: []
    #: (understanding, output_dir) -> IterationMove | None — the tree edit.
    move: Optional[Callable[[dict, str], Any]] = None

    @property
    def out(self) -> str:
        return str(self.output_dir)

    def doc(self) -> dict:
        from services.smith.engine_blueprint_adapter import load_engine_doc
        return load_engine_doc(self.out) or {}


Perform = Callable[[Ctx, dict], Outcome]


def _s(u: dict, key: str) -> str:
    return str(u.get(key) or "").strip()


def _field_name(u: dict) -> str:
    f = u.get("field")
    return str(f.get("name") or "").strip() if isinstance(f, dict) else str(f or "").strip()


# --------------------------------------------------------------------------- #
# The look, the menu, the processes, the sections
# --------------------------------------------------------------------------- #

def restyle(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.restyle import run
    return from_seam(run(ctx.out, _s(u, "change") or ctx.ask, reasoning=ctx.reasoning),
                     ok="Restyled.", fail="I could not restyle the application and have changed nothing.")


def logo(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.brand_logo_change import run
    return from_seam(run(ctx.out, remove=(u["verb"] == "remove_logo"), reasoning=ctx.reasoning),
                     fail="I could not change the logo and have changed nothing.")


def navigation(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.navigation_change import run
    return from_seam(run(ctx.out, _s(u, "change") or ctx.ask, reasoning=ctx.reasoning),
                     ok="Changed the menu.", fail="I could not change the menu and have changed nothing.")


def workflow(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.workflow_change import run
    verb = u["verb"]
    return from_seam(run(ctx.out, verb, workflow=_s(u, "workflow") or ctx.ask,
                         change=_s(u, "change"), route=_s(u, "route"), reasoning=ctx.reasoning),
                     fail=f"I could not {verb.replace('_', ' ')} and have changed nothing.")


def access(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.access_change import run
    return from_seam(run(ctx.out, _s(u, "change") or ctx.ask, reasoning=ctx.reasoning),
                     fail="I could not change who may do what, and have changed nothing.")


def rule(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.rule_change import run
    verb = u["verb"]
    return from_seam(run(ctx.out, verb, rule=_s(u, "rule") or ctx.ask, change=_s(u, "change"),
                         reasoning=ctx.reasoning),
                     fail=f"I could not {verb.replace('_', ' ')} and have changed nothing.")


def entity(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.entity_change import consequences, run
    verb = u["verb"]
    ref = _s(u, "entity") or ctx.ask
    if verb == "remove_entity":
        said = consequences(ctx.doc(), ref)
        takes: list[str] = []
        if said.get("found"):
            if said["pages"]:
                takes.append(f"{len(said['pages'])} screen(s) — {', '.join(said['pages'])} — "
                             "retired and taken off the menu")
            if said["workflows"]:
                takes.append(f"{len(said['workflows'])} automatic process(es) — "
                             f"{', '.join(said['workflows'])} — stopped, and their buttons "
                             "taken off every screen")
            if said["pointing"]:
                takes.append("records that point at it: " + ", ".join(said["pointing"]))
        gate = confirm_cascade(ctx, "remove_entity", ref, takes)
        if gate is not None:
            return gate
    return from_seam(run(ctx.out, verb, entity=ref, reasoning=ctx.reasoning),
                     fail=f"I could not {verb.replace('_', ' ')} and have changed nothing.")


def definition(ctx: Ctx, u: dict) -> Outcome:
    """Fields, requirements, product, APIs and integrations."""
    verb = u["verb"]
    if verb in ("rename_field", "remove_field"):
        from services.smith.field_change import run
        out = run(ctx.out, verb, entity=_s(u, "entity"), field=_field_name(u),
                  new_value=_s(u, "new_value"), reasoning=ctx.reasoning)
    else:
        from services.smith.definition_change import run
        text = {"add_requirement": "requirement", "edit_requirement": "requirement",
                "remove_requirement": "requirement", "add_api": "api", "remove_api": "api",
                "add_integration": "integration", "remove_integration": "integration",
                "edit_product": "change"}.get(verb, "")
        out = run(ctx.out, verb, text=_s(u, text) or ctx.ask, change=_s(u, "change"),
                  reasoning=ctx.reasoning)
    return from_seam(out, fail=f"I could not {verb.replace('_', ' ')} and have changed nothing.")


def remove_field(ctx: Ctx, u: dict) -> Outcome:
    """A column's data is the one thing undo does not bring back, so it is
    named before it goes, with everywhere the box is used."""
    from services.smith.field_change import consequences
    ent, name = _s(u, "entity"), _field_name(u)
    said = consequences(ctx.doc(), ent, name)
    takes: list[str] = []
    if said.get("found"):
        takes = ["everything written in it so far, which cannot be brought back"]
        if said["used"]:
            takes.append("it comes off " + ", ".join(said["used"]))
        if said["rules"]:
            takes.append("rules that check it are retired: " + ", ".join(said["rules"]))
        if said["workflows"]:
            takes.append("processes that use it are re-authored: " + ", ".join(said["workflows"]))
    gate = confirm_cascade(ctx, "remove_field", f"{ent}.{name}", takes)
    return gate if gate is not None else definition(ctx, u)


def add_field(ctx: Ctx, u: dict) -> Outcome:
    ent = _s(u, "entity")
    f = u.get("field") if isinstance(u.get("field"), dict) else {}
    name = str(f.get("name") or "").strip()
    if not ent or not name:
        return Outcome(status="asked",
                       said="Which record should it go on, and what should the box be called?")
    t = str(f.get("type") or "string").lower().strip()
    bp_type = ({"text": "string", "varchar": "string", "str": "string", "int": "integer",
                "integer": "integer", "number": "integer", "decimal": "decimal",
                "numeric": "decimal", "float": "decimal", "money": "decimal", "bool": "boolean",
                "boolean": "boolean", "date": "date", "datetime": "timestamp",
                "timestamp": "timestamp"}.get(t, t)) or "string"
    if not (Path(ctx.out) / ".forge" / "blueprint" / "current.json").exists():
        from services.fix_applier import _apply_add_field
        out = _apply_add_field(ctx.out, {"proposedFix": {"seam": "add_field",
                                                          "patch": {"entity": ent, "field": f}}}, git=False)
        if not out.get("applied"):
            return Outcome(status="needs_user",
                           said=str(out.get("reason") or f"I could not add {name!r} to {ent}."))
        touched = [c["path"] for c in (out.get("changes") or []) if c.get("path")]
        return Outcome(status="resolved", touched=touched,
                       said=(f"Added **{name}** to **{ent}** — a {bp_type} box, optional, so records "
                             "that already exist simply have it empty and nothing is rebuilt"
                             + (f". Updated: {', '.join(touched[:6])}." if touched else ".")
                             + " Say which screen should show it and I will put it there."))
    try:
        from services.blueprint.service import BlueprintService
        from services.smith import field_change as fc
        from services.smith.section_change import SectionChangeError
        svc = BlueprintService.load(output_dir=ctx.out)
        app_root = Path(ctx.out) / "app"
        if not (app_root / "src").exists():
            app_root = Path(ctx.out)
        try:
            out = fc.add_field(svc, ent, {"name": name, "type": bp_type,
                                          "label": str(f.get("label") or "")},
                               app_root=str(app_root), reasoning=ctx.reasoning)
        except SectionChangeError as exc:
            return Outcome(status="needs_user", said=str(exc))
    except Exception as exc:  # noqa: BLE001 — a turn degrades, it does not crash
        logger.exception("add_field failed for %s.%s", ent, name)
        return Outcome(status="needs_user", said=f"I could not add {name!r} to {ent}: {exc}")
    return Outcome(status="resolved", said=fc.summary_of("add_field", out),
                   touched=list(out.get("edited_paths") or []))


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #

def compose(ctx: Ctx, u: dict) -> Outcome:
    """Compose a screen, or add sections to one — `compose.run`, the one entry
    the tool and the verb share. The composer's refusal is a finding: "did not
    compile: TS2322" is the compiler speaking, and a loop that can read the
    code gets to brief the engineer again."""
    from services.smith.compose import run
    verb, route = u["verb"], _s(u, "route")
    change = _s(u, "change")
    request = f"{change}\n\n(In their words: \"{ctx.ask}\")" if change else ctx.ask
    out = run(ctx.out, verb, route=route, widgets=[str(w) for w in (u.get("widgets") or [])],
              request=request, reasoning=ctx.reasoning)
    if not out.get("applied"):
        reason = str(out.get("reason") or f"I could not {verb.replace('_', ' ')} {route} "
                                          "and have changed nothing.")
        return Outcome(status="needs_user", said=reason, finding=f"{route} was not changed: {reason}")
    touched = list(out.get("edited_paths") or [])
    missing = [str(m) for m in (out.get("missing") or [])]
    if missing:
        return Outcome(
            status="needs_user", touched=touched,
            said=("I changed **" + route + "**, but the new screen does not show what you "
                  "asked for:\n" + "\n".join(f"- {m}" for m in missing)
                  + "\n\nIf it is a field of the record, ask me to add the field to the "
                    "entity and I will put it on the form directly. Otherwise say what it "
                    "should contain and I will compose the screen again."),
            finding=(f"{route} was composed, but the code does not draw: {', '.join(missing)}. "
                     "The page changed; what was asked for is not on it. Either the missing "
                     "thing is a field the record does not have — add it — or the page must "
                     "be composed again saying what it should contain."))
    return Outcome(status="resolved", touched=touched,
                   said=(str(out.get("diff_summary") or f"I updated {route}.")
                         + (f"\n\nUpdated: {', '.join(touched[:6])}." if touched else "")))


def remove_page(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.page_change import consequences, run, why_not
    route = _s(u, "route")
    doc = ctx.doc()
    why = why_not(doc, route)
    if why:
        return Outcome(status="needs_user", said=why)
    said = consequences(doc, route)
    takes: list[str] = []
    if said.get("found"):
        if said["menu"]:
            takes.append("it comes off the menu (" + ", ".join(said["menu"]) + ")")
        if said["links"]:
            takes.append(f"{len(said['links'])} link(s) to it come off other screens: "
                         + ", ".join(said["links"][:6]))
        if said["landing"]:
            takes.append("the application stops opening on it, and opens on whatever the "
                         "menu leads with instead")
        if said["launches"]:
            takes.append("processes started from it lose the screen they start from: "
                         + ", ".join(said["launches"]))
        if said["widgets"]:
            takes.append(f"{said['widgets']} widget(s) on it are retired with it")
    gate = confirm_cascade(ctx, "remove_page", route, takes)
    if gate is not None:
        return gate
    return from_seam(run(ctx.out, route=route, reasoning=ctx.reasoning),
                     ok="Removed the screen.",
                     fail="I could not remove that screen and have changed nothing.")


def tree_edit(ctx: Ctx, u: dict) -> Outcome:
    """`rename`, `remove`, `reorder`: a label on a layout page, proved by git.

    A coded page is changed as code — the tree edit changes nothing on screen
    there — so it goes to the composer with the ask as its brief. On a layout
    page the move edits the tree by label and the checks at the bottom ask git
    what actually changed, never the move: the diff must mention the label and
    touch the screen that was named, and no guard that passed may now fail.
    Each of those is a finding.
    """
    verb = u["verb"]
    if verb == "remove":
        u = {**u, "new_value": ""}
    target, label = _s(u, "target_file"), _s(u, "element_label")
    doc = ctx.doc()

    if target:
        from services.smith.compose import _page_for_route, code_row
        coded = _page_for_route(doc, target)
        if coded is not None and code_row(doc, str(coded.get("id"))) is not None:
            return compose(ctx, {**u, "verb": "compose_route", "route": coded.get("route")})
    if verb == "reorder":
        from services.smith.limits import answer
        said, options = answer(verb, u, doc)
        return Outcome(status="needs_user", said=said, options=options)
    if not target:
        from services.smith.slot_options import options_for
        return Outcome(status="asked", said="Which screen?", options=options_for("route", doc))

    if label:
        from services.smith.labels import collect, describe, normalise, resolve
        found = resolve(doc, label, target)
        if found.get("candidates"):
            return Outcome(status="asked",
                           said=f"There is more than one “{label}”. Which one did you mean?",
                           options=[describe(c) for c in found["candidates"]][:5])
        if found.get("text"):
            if found["text"] != label:
                u, label = {**u, "element_label": found["text"]}, found["text"]
        else:
            want = normalise(target)
            on_screen = [c["text"] for c in collect(doc)
                         if want and want in (normalise(c.get("route") or ""),
                                              normalise(c.get("page") or ""))][:5]
            if on_screen:
                return Outcome(status="asked", options=on_screen,
                               said=(f"I could not find “{label}” on {target}, so I have "
                                     "changed nothing. Is it one of these?"))

    if ctx.move is None:
        return Outcome(status="needs_user", said="No tree editor is wired for this project.")
    baseline = snapshot_baseline(ctx.out, guards_fn=ctx.guards)
    move = ctx.move(u, ctx.out)
    if move is None:
        return Outcome(status="no_op",
                       said=(f"I looked for “{label}” in {target} and could not find it, so I "
                             "have changed nothing rather than editing the nearest thing. If it "
                             "is there under different wording, tell me the exact text."))

    modified_now = set(git_status_modified(ctx.out))
    baseline_tree = baseline.get("tree") or {}
    touched = sorted((modified_now - set(baseline.get("status") or []))
                     | set(tree_changes(ctx.out, baseline_tree)))
    if not touched:
        return Outcome(
            status="needs_user",
            said=(f"I tried the move `{move.move_name}` but nothing actually changed on disk. "
                  "Something short-circuited before the write."),
            options=["retry with a different approach", "leave it and I'll come back later"],
            finding=(f"The move `{move.move_name}` ran and the working tree is unchanged: "
                     "nothing was written. Whatever it was told to edit, it did not find."))
    diff = git_diff_lines(ctx.out, touched) + tree_diff_lines(ctx.out, baseline_tree, touched)
    summary = _diff_summary_line(touched, diff)
    lower = {p.lower() for p in touched}
    if not any(target.lower() in p or p in target.lower() for p in lower):
        return Outcome(
            status="needs_user", touched=touched, diff_summary=summary,
            said=f"I edited {touched} but you asked about `{target}`. That's the wrong file.",
            options=["retry against the correct file", "roll back and try again", "keep this edit anyway"],
            finding=(f"git says the edit landed on {touched}, not on `{target}`, which is what "
                     "was named. The wrong thing was edited — the ask may be right and the "
                     "target wrong."))
    if label and label.lower() not in diff.lower():
        return Outcome(
            status="needs_user", touched=touched, diff_summary=summary,
            said=f"I edited `{target}` but the diff doesn't touch anything labeled '{label}'.",
            options=["retry — target the correct element", "roll back and try again", "keep this edit anyway"],
            finding=(f"`{target}` was edited, but the diff mentions nothing labelled '{label}' — "
                     "something nearby was changed instead. That label may not be what the "
                     "thing is actually called."))
    new_failures = guard_delta(baseline.get("guards"), ctx.guards(ctx.out) or [])
    if new_failures:
        broke = "; ".join(f"{f.get('guard') or '?'}: {f.get('message') or '?'}" for f in new_failures[:3])
        return Outcome(
            status="needs_user", touched=touched, diff_summary=summary,
            said=f"The edit landed on `{target}` but broke {len(new_failures)} guard(s): {broke}.",
            options=["retry with the guard feedback", "roll back this edit", "keep it — I'll deal with the guards later"],
            finding=(f"The edit landed on `{target}` and broke {len(new_failures)} guard(s) that "
                     f"passed before it: {broke}."))

    from services.smith_blueprint import Blueprint
    bp = Blueprint.load(project_id=ctx.project_id, output_dir=ctx.out)
    bp.append_change_log(
        at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        user_ask=ctx.message, smith_move=move.move_name, diff_summary=summary,
        verified_by=["git status", "git diff", "guard delta empty"],
        why=_s(u, "desired_behavior") or "matches user ask", source="smith")
    bp.save()
    new_text = _s(u, "new_value")
    if label and new_text:
        said = f"Done — **{label}** on {target} now says **{new_text}**."
    elif label:
        said = f"Done — **{label}** is off {target}, and the screen no longer offers what it did."
    else:
        was, now = _s(u, "current_behavior"), _s(u, "desired_behavior")
        said = f"Done — {target}: {was} → {now}." if was and now else f"Done — {target} has been changed."
    return Outcome(status="resolved", said=said, touched=touched, diff_summary=summary)


# --------------------------------------------------------------------------- #
# Outside services and designs
# --------------------------------------------------------------------------- #

def connect_service(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.email_connect import run
    return from_seam(run(ctx.out, service=_s(u, "integration"), reasoning=ctx.reasoning),
                     fail="I could not connect that and have changed nothing.")


def disconnect_design(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.design_disconnect import disconnect_and_recompose
    out = disconnect_and_recompose(ctx.out, ctx.message, reasoning=ctx.reasoning)
    if not out.get("applied"):
        return Outcome(status="no_op", said=str(out.get("reason") or "No design is connected."))
    sources = ", ".join(out.get("sources") or []) or "the design"
    said = (f"Disconnected {sources}. {len(out.get('unbound') or [])} screen(s) no longer build "
            f"from a frame; {len(out.get('completed') or [])} step(s) re-ran to compose them "
            "from the component library.")
    if out.get("failed"):
        said += f" These did not finish: {', '.join(out['failed'])}."
    return Outcome(status="resolved", said=said,
                   diff_summary=(f"version {out.get('version')}: design disconnected, "
                                 f"{out.get('dropped_layouts', 0)} drawn layout(s) retired"))


_SCOPE_QUESTION = ("Before I pull it in — is this design the SPECIFICATION or a REFERENCE?\n\n"
                   "• Specification: I build exactly the screens on it and nothing else.\n"
                   "• Reference: the screens become requirements and the design language, "
                   "and the application is built around them — usually more pages than "
                   "designs.\n\nSay “specification” or “reference”.")


def connect_figma(ctx: Ctx, u: dict) -> Outcome:
    """Smith never asks for the token — a variable NAME, which is not a secret."""
    from services.figma.url import parse
    from services.smith.figma_connect import FigmaConnectError, connect
    from services.smith.understand_ask import _design_scope
    url, token_env = _s(u, "figma_url"), _s(u, "token_env")
    if not url:
        return Outcome(status="asked", said="Which Figma file? Paste the link from Figma's Share "
                                            "dialog and I'll pull the screens and tokens out of it.")
    if not token_env:
        return Outcome(status="asked", said=(
            "Which environment variable holds your Figma token? I need the NAME — `FIGMA_TOKEN`, "
            "for example — not the token itself. Anything you type here is written to the "
            "conversation log, so a credential must not go in it; export the token in the "
            "backend's environment and tell me what you called it."))
    if parse(url) is None:
        return Outcome(status="needs_user", said=(
            f"That does not look like a Figma URL: {url!r}. I need the link from Figma's Share "
            "dialog, like https://figma.com/design/<key>/<name>?node-id=1-2"))
    treat_as = _design_scope(u.get("treat_as"))
    if not treat_as:
        # ASKED ONCE, BECAUSE THE TWO ANSWERS BUILD DIFFERENT APPLICATIONS — and
        # the question says what each costs: "specification" quietly means no
        # sign-in and no create forms, and that belongs in the question, not
        # in the built app.
        return Outcome(status="asked", options=["Specification", "Reference"], said=(
            "Before I pull it in — is this design the SPECIFICATION or a REFERENCE?\n\n"
            "• Specification: I build exactly the screens you drew and nothing else. No "
            "sign-in, no lists behind the numbers, no forms to create what they show, "
            "unless they are in the file.\n"
            "• Reference: the screens become requirements and the design language, and "
            "the application is built around them — usually more pages than frames.\n\n"
            "Say “specification” or “reference”."))
    try:
        out = connect(ctx.out, figma_url=url, token_env=token_env, treat_as=treat_as)
    except FigmaConnectError as exc:
        return Outcome(status="needs_user", said=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("figma connect failed for %s", ctx.out)
        return Outcome(status="needs_user", said=f"I could not read that Figma file: {type(exc).__name__}.")
    return Outcome(status="resolved", said=out["summary"])


def connect_uxpilot(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.understand_ask import _design_scope
    from services.smith.uxpilot_connect import UxPilotConnectError, connect
    from services.uxpilot.url import parse
    ref, key_env = _s(u, "uxpilot_ref"), _s(u, "key_env")
    if not ref:
        return Outcome(status="asked", said="Which UX Pilot page? Paste the page's URL or its id "
                                            "and I'll pull the designs and theme out of it.")
    if not key_env:
        return Outcome(status="asked", said=(
            "Which environment variable holds your UX Pilot API key? I need the NAME — "
            "`UXPILOT_API_KEY`, for example — not the key itself. Anything you type here is "
            "written to the conversation log, so a credential must not go in it; add it under "
            "Settings → Integrations → UX Pilot and tell me what it is called."))
    if parse(ref) is None:
        return Outcome(status="needs_user", said=(
            f"That does not look like a UX Pilot page: {ref!r}. I need the page id, or the "
            "page's URL from UX Pilot."))
    treat_as = _design_scope(u.get("treat_as"))
    if not treat_as:
        return Outcome(status="asked", said=_SCOPE_QUESTION, options=["Specification", "Reference"])
    try:
        out = connect(ctx.out, uxpilot_ref=ref, key_env=key_env, treat_as=treat_as)
    except UxPilotConnectError as exc:
        return Outcome(status="needs_user", said=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("uxpilot connect failed for %s", ctx.out)
        return Outcome(status="needs_user", said=f"I could not read that UX Pilot page: {type(exc).__name__}.")
    return Outcome(status="resolved", said=out["summary"])


# --------------------------------------------------------------------------- #
# The application as a whole; people; records; what happened
# --------------------------------------------------------------------------- #

def revert(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.revert import run
    return from_seam(run(ctx.out, reasoning=ctx.reasoning), ok="Undone.", fail="I could not undo that.")


def guide(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.handover import run, summary_of
    out = run(ctx.out, app_root=str(Path(ctx.out) / "app"), reasoning=ctx.reasoning)
    if not out.get("applied"):
        return Outcome(status="needs_user", said=str(out.get("reason") or "I could not write the guide."))
    return Outcome(status="resolved", said=summary_of(out), touched=list(out.get("edited_paths") or []))


def spend(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.spend import run
    out = run(ctx.out, reasoning=ctx.reasoning)
    if not out.get("applied"):
        return Outcome(status="needs_user", said=str(out.get("reason") or "I could not read what this has cost."))
    return Outcome(status="resolved", said=str(out.get("diff_summary") or ""))


def import_data(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.data_import import run
    return from_seam(run(ctx.out, _s(u, "entity"), message=ctx.message, reasoning=ctx.reasoning),
                     ok="Loaded.", fail="I could not load that and nothing has been written.")


def export_data(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.data_export import run
    out = run(ctx.out, _s(u, "entity"), project_id=str(ctx.project_id or ""), reasoning=ctx.reasoning)
    if not out.get("applied"):
        return Outcome(status="needs_user", said=str(out.get("reason") or "I could not produce that file."))
    return Outcome(status="no_op", said=str(out.get("diff_summary") or "Exported."))


def accounts(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.accounts import run
    return from_seam(run(ctx.out, u["verb"], email=_s(u, "email"), person=_s(u, "person"),
                         name=_s(u, "person_name"), role=_s(u, "role"), reasoning=ctx.reasoning),
                     fail="I could not change that login, and have changed nothing.")


def incident(ctx: Ctx, u: dict) -> Outcome:
    from services.incident_ledger import KIND_CRASH, KIND_SLOW
    from services.smith.incidents import run
    out = run(ctx.out, kind=KIND_SLOW if u["verb"] == "explain_slowness" else KIND_CRASH)
    return Outcome(status="needs_user", said=str(out.get("answer") or ""),
                   options=list(out.get("options") or []))


def records_out(ctx: Ctx, u: dict) -> Outcome:
    from services.smith.records_out import run
    out = run(ctx.out, str(ctx.project_id), kind="backup" if u["verb"] == "back_up" else "export",
              entity=_s(u, "entity"), reasoning=ctx.reasoning)
    if not out.get("applied"):
        return Outcome(status="needs_user",
                       said=str(out.get("reason") or "I could not get the records out of this application."))
    return Outcome(status="resolved", said=str(out.get("diff_summary") or ""))


def rebuild(ctx: Ctx, u: dict) -> Outcome:
    """A chat turn cannot start a run, so it must not imply that it can."""
    stale = ""
    if (Path(ctx.out) / ".forge" / "blueprint" / "current.json").exists():
        try:
            from services.blueprint import approval
            from services.blueprint.service import BlueprintService
            doc = BlueprintService.load(output_dir=ctx.out).doc
            if approval.state_of(doc, "plan") == "stale":
                last = approval.latest(doc, "plan") or {}
                stale = (f"the plan was approved at version {last.get('version', '?')} and the "
                         f"definition is now at version {doc.get('version', '?')} — it has changed "
                         "since and must be reviewed again")
        except Exception:  # noqa: BLE001 — a gate that cannot be read does not block the answer
            logger.exception("could not read the plan gate")
    if stale:
        return Outcome(status="needs_user", said=(
            f"Not building on the current approval: {stale}. Open the “Definition ready to "
            "review” card above and press “Approve and build” to renew it against the "
            "definition as it now stands; the build then proceeds."))
    return Outcome(status="needs_user", said=(
        "Building the whole application is started from the definition, not from chat: open "
        "the “Definition ready to review” card above and press “Approve and build”. That runs "
        "the pages, the data and the workflows, which takes a few minutes.\n\nI can still "
        "change one screen from here — name the route and I will rebuild that."))


def section_write(ctx: Ctx, u: dict) -> Outcome:
    """The three asks that used to be refused, made through `write_section`.

    `rename_entity`, `change_field_type` and `edit_api` were `limits.py`'s
    honest refusals: each names a change to a section the verb table had no
    seam for. The seam exists now — the loop's `write_section` briefs the
    owning agent — so the verb composes the brief from what was said and the
    outcome is the section's. What the refusal used to warn about (a type
    change loses what is in the box; a rename reaches pages and processes) is
    in the brief, and in the reply, so the loop can follow it up.
    """
    from services.smith import writes
    verb = u["verb"]
    ent, new = _s(u, "entity"), _s(u, "new_value")
    field = _field_name(u)
    if verb == "rename_entity":
        section, subject = "data.entities", ""
        brief = (f"Rename the record kind **{ent}** to **{new}** — its name and label, and its table "
                 "name where it is derived from the name. Keep its id, every field, every "
                 "relationship and every constraint exactly as they are. Pages, workflows and "
                 f"rules that say \"{ent}\" are separate sections; report them rather than touching them.")
    elif verb == "change_field_type":
        section, subject = "data.entities", ""
        want = _s(u, "change") or _s(u, "field") if not isinstance(u.get("field"), dict) else str((u.get("field") or {}).get("type") or _s(u, "change"))
        brief = (f"Change the type of the field **{field}** on **{ent}** to {want or 'what was asked'}. "
                 "Keep the field's name, label and everything else on the entity. If existing values "
                 "cannot be carried across, say so in the migration rather than silently dropping them.")
    else:  # edit_api
        section, subject = "apis", ""
        brief = (f"Change the endpoint **{_s(u, 'api')}**: {_s(u, 'change') or ctx.ask}. Keep its "
                 "path and method unless the change is to them; keep every other endpoint as it is.")
    out = writes.write_section(ctx.out, section, brief, subject=subject, reasoning=ctx.reasoning)
    said = str(out.get("said") or "")
    if verb == "rename_entity" and out.get("applied") and not out.get("finding"):
        from services.smith.entity_change import consequences
        who = consequences(ctx.doc(), new) or consequences(ctx.doc(), ent)
        rest = [s for s in (who.get("pages") or []) + (who.get("workflows") or []) if s]
        if rest:
            said += (f" Still saying \"{ent}\" and worth a look: " + ", ".join(rest[:8]) + ".")
    return Outcome(status="resolved" if out.get("applied") and not out.get("finding") else "needs_user",
                   said=said, touched=list(out.get("touched") or []),
                   finding=str(out.get("finding") or ""))


def honest_refusal(ctx: Ctx, u: dict) -> Outcome:
    """`limits.answer`: why not, and the nearest thing that works, as chips.
    Only `reorder` on a layout page reaches this now (see `tree_edit`)."""
    from services.smith.limits import answer
    said, options = answer(u["verb"], u, ctx.doc())
    return Outcome(status="needs_user", said=said, options=options)


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #

def confirm_cascade(ctx: Ctx, verb: str, target: str, takes: list[str]) -> Outcome | None:
    """Show what a change takes with it and wait for a yes — or None when the
    yes is already in hand, kept against a fingerprint of THIS operation."""
    from services.smith import confirm
    if not takes:
        return None
    if confirm.granted(ctx.out, ctx.message, verb, target):
        return None
    confirm.remember(ctx.out, confirm.fingerprint(verb, target))
    return Outcome(status="asked", options=[confirm.YES_LABEL, confirm.NO_LABEL],
                   said=("That does not only remove what you named. It also takes:\n"
                         + "\n".join(f"- {c}" for c in takes) + "\n\nShall I go ahead?"))


def _diff_summary_line(paths: list[str], diff: str) -> str:
    n = len(paths)
    if not diff:
        return f"{n} file(s) touched"
    added = diff.count("\n+") - diff.count("\n+++")
    removed = diff.count("\n-") - diff.count("\n---")
    files = ", ".join(paths[:3]) + (f", +{n - 3} more" if n > 3 else "")
    return f"{files} | +{added} -{removed}"


#: verb -> how it is carried out. Compared against `REQUIRED_BY_VERB` by test.
PERFORM: dict[str, Perform] = {
    "rename": tree_edit, "remove": tree_edit, "reorder": tree_edit,
    "restyle": restyle, "set_logo": logo, "remove_logo": logo,
    "edit_navigation": navigation,
    "add_workflow": workflow, "edit_workflow": workflow, "remove_workflow": workflow,
    "edit_access": access,
    "add_rule": rule, "edit_rule": rule, "remove_rule": rule,
    "add_entity": entity, "remove_entity": entity,
    "add_field": add_field, "rename_field": definition, "remove_field": remove_field,
    "add_requirement": definition, "edit_requirement": definition, "remove_requirement": definition,
    "edit_product": definition, "add_api": definition, "remove_api": definition,
    "add_integration": definition, "remove_integration": definition,
    "connect_service": connect_service, "connect_figma": connect_figma,
    "connect_uxpilot": connect_uxpilot, "disconnect_design": disconnect_design,
    "compose_route": compose, "add_widgets": compose, "remove_page": remove_page,
    "revert": revert, "write_guide": guide, "spend": spend,
    "import_data": import_data, "export_data": export_data,
    "add_login": accounts, "remove_login": accounts, "reset_login": accounts,
    "explain_crash": incident, "explain_slowness": incident, "back_up": records_out,
    "rebuild": rebuild,
    "rename_entity": section_write, "change_field_type": section_write, "edit_api": section_write,
}


def perform(ctx: Ctx, verb: str, understanding: dict) -> Outcome:
    fn = PERFORM.get(verb)
    if fn is None:
        raise KeyError(verb)
    return fn(ctx, {**understanding, "verb": verb})


__all__ = ["Ctx", "PERFORM", "Outcome", "perform", "confirm_cascade"]
