"""Before there is an application: the clarifier as a read, the definition as a write.

The Blueprint router used to run this phase itself: ask the clarifier one
question a turn, refuse a brief that describes a page with nothing to do,
then "Let me define that first" and the definition DAG. Those are the same
three things a turn does anywhere else — look, refuse with a reason, write
through the seam — so they are the loop's now. `open_decisions` is
`clarify_brief` as a read: what the brief so far leaves unsaid, as questions
with their answers as chips. `define_application` is the definition as a
write: the domain nodes of the DAG, through the same executor and observer a
build uses, parked at review for the person to accept.

WHAT STAYS THE ROUTER'S. The consents: "Approve and build" is a card, and the
build it starts is the DAG's, not a turn's. The card after a definition lands
is emitted by the router once the turn returns, because the panel is the
router's to draw.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.smith import brief as brief_mod
from services.smith4.outcome import Outcome
from services.smith4.verbs import Ctx

logger = logging.getLogger(__name__)

#: How many of the person's turns the clarifier may spend asking. After that,
#: define with what is known — a clarifier that can always find one more
#: question would never let an application exist.
MAX_CLARIFY_TURNS = 4


def brief_of(ctx: Ctx) -> str:
    """Everything the person has said, with the documents they supplied."""
    return brief_mod.with_documents(brief_mod.brief_from(ctx.history, ctx.message), ctx.evidence)


def user_turns(ctx: Ctx) -> int:
    return sum(1 for t in ctx.history
               if str(t[0] if isinstance(t, (tuple, list)) else getattr(t, "role", "")) == "user")


def _turn_text(turn: object) -> tuple[str, str]:
    if isinstance(turn, (tuple, list)) and len(turn) == 2:
        role, text = turn
    else:
        role, text = getattr(turn, "role", ""), getattr(turn, "text", "")
    return str(role), str(text or "")


def platform_asked(ctx: Ctx) -> int:
    """How many times Smith has put the platform question: a turn of its own that names the options."""
    from services.blueprint import app_target
    asked = 0
    for role, text in map(_turn_text, ctx.history):
        low = text.lower()
        if role != "user" and ("where will people use it" in low
                               or sum(1 for _s, label in app_target.OPTIONS if label.lower() in low) >= 2):
            asked += 1
    return asked


def settle_platform(ctx: Ctx) -> str | None:
    """Where people will use the app, if it is settled now: already kept, or answered by this turn's message.

    ONLY A REPLY TO THE QUESTION COUNTS. The brief itself may say "a native phone app for iPhone and Android"; that
    is a wish, not an answer to the five choices, and reading it as one picked an option nobody was offered. So the
    message is read only once the question has been asked, and a message that names no choice is asked about once more;
    after that, or when nobody can be asked, the app is a website: the choice that adds nothing the person did not
    ask for. The choice is written down either way, so a build never starts without one."""
    from services.blueprint import app_target

    chosen = app_target.read(ctx.out)
    if chosen:
        return chosen
    asked = platform_asked(ctx)
    if asked:
        said = app_target.parse_choice(ctx.message)
        if said:
            app_target.write(ctx.out, said)
            return said
    if asked >= 2 or getattr(ctx, "unattended", False) or (not asked and user_turns(ctx) >= MAX_CLARIFY_TURNS):
        # Asked twice without a pick, nobody to ask, or a conversation too long to start with a new question.
        app_target.write(ctx.out, "web")
        return "web"
    return None


def platform_question(ctx: Ctx) -> str:
    """The instruction that makes Smith ask where people will use the app — first, in these words, with these chips."""
    from services.blueprint import app_target

    again = ("They were asked this already and did not pick one of the five: say so in one short line, "
             "then ask it again. " if platform_asked(ctx) else "")
    chips = "; ".join(label for _surface, label in app_target.OPTIONS)
    return ("THE PLATFORM IS NOT CHOSEN, AND IT IS ASKED FIRST. " + again +
            "Ask it with `ask_user`: the `question` is the text below, word for word, and the `options` are exactly "
            f"these five chips, in this order: {chips}. Ask nothing else this turn, and do not choose for them "
            "or define the application.\n\nQUESTION:\n" + app_target.QUESTION)


def canonical_platform_ask(ctx: Ctx, args: dict) -> dict:
    """While the platform is still open on a new app, Smith's question IS the platform question, in its own words and with
    its five chips. The model is told to pass them word for word, but it had merged the limits into one paragraph; the
    words are fixed text, so they are put back here rather than trusted to a model."""
    from services.blueprint import app_target
    from services.smith4.context import defined

    if defined(ctx.out) or not _is_platform_question(args):
        return args                      # an app exists, or this is some other question: it is the model's own
    if settle_platform(ctx) is not None:
        return args
    return {**args, "question": app_target.QUESTION, "options": [label for _surface, label in app_target.OPTIONS]}


def _is_platform_question(args: dict) -> bool:
    """Is the model's question the one about where people will use the app? By its words or by its chips."""
    from services.blueprint import app_target

    said = str(args.get("question") or "").lower()
    chips = " | ".join(str(o).lower() for o in (args.get("options") or []))
    named = sum(1 for _surface, label in app_target.OPTIONS if label.lower() in said or label.lower() in chips)
    return "where will people use" in said or named >= 2 or ("pwa" in said and "native" in said)


def open_decisions(ctx: Ctx, args: dict) -> str:
    """The decisions the brief so far leaves open, as questions with chips.

    The first is always where people will use the app (`app_target`), asked in fixed words so the answer can be read
    exactly; the rest are the clarifier's. Silence is the default for those: a brief that says what the application
    is for and what people do in it gets no question. The cap is structural — past it, the answer is "define with
    what is known"."""
    from services.smith.clarify_brief import clarify_brief, company_palette_option
    from services.smith.figma_connect import find_in as figma_in
    from services.smith.uxpilot_connect import find_in as uxpilot_in

    brief = brief_of(ctx)
    if not brief.strip():
        return "Nothing has been asked for yet. There is no brief to clarify."
    if settle_platform(ctx) is None:
        return platform_question(ctx)
    if user_turns(ctx) >= MAX_CLARIFY_TURNS:
        return (f"The person has answered {user_turns(ctx)} times already; asking more would be "
                "interrogating. Define with what is known.")
    design = bool(figma_in(brief) or uxpilot_in(brief)) or brief_mod.has_design_references(ctx.project_id)
    offer = brief_mod.design_language_offer(Path(ctx.out))
    palette = company_palette_option(offer[0], offer[1]) if offer else ""
    asked = clarify_brief(brief, design_attached=design, company_palette=palette)
    if not asked:
        return "The brief stands on its own: nothing material is left unsaid. Define it."
    lines = ["Open decisions, one per turn — ask the first with its options as chips:"]
    for item in asked:
        options = "; ".join(item.get("options") or [])
        lines.append(f"- {item['question']}" + (f"  [options: {options}]" if options else ""))
    return "\n".join(lines)


def define_application(ctx: Ctx, args: dict) -> dict:
    """Author what the application is — the DAG's domain nodes — and stop at
    review. Returns the write envelope: `applied`, `said`, `finding`,
    `touched`."""
    from services.blueprint.executors import RunUsage, make_executor, tiered_router
    from services.blueprint.observer import anthropic_observer
    from services.blueprint.orchestrator import completed_nodes, nodes_recorded_done, run
    from services.blueprint.service import BlueprintService
    from services.smith.smith import domain_nodes

    # THE PERSON'S WORDS ARE THE DESCRIPTION; THE DOCUMENTS ARE STORED BESIDE
    # IT. `brief_of` adds every supplied document's text, which is right for
    # the clarifier reading this turn and wrong for `application.description`:
    # every agent reads the description, so a BRD written into it was read
    # twice by the two that read documents and paid for by every other.
    brief = str(args.get("brief") or "").strip() or brief_mod.brief_from(ctx.history, ctx.message)
    if not brief:
        return _finding("There is nothing to define: the person has not said what the application is for.")
    if brief_mod.is_functionless(brief):
        return _finding("That describes a page with nothing to do — it would only show some text. "
                        "What should the app let people DO (create or manage something, sign in, "
                        "run a workflow)? Ask that; do not define it.")
    output_dir = ctx.out
    existing = Path(output_dir) / ".forge" / "blueprint" / "current.json"
    try:
        if existing.is_file():
            svc = BlueprintService.load(output_dir=output_dir)
            prior = str((svc.doc.get("application") or {}).get("description") or "")
            merged = brief if not prior else (prior if brief in prior else f"{prior}\n\n{brief}")
            svc.doc.setdefault("application", {})["description"] = merged
            svc.validate(); svc.save()
        else:
            # THE PLATFORM IS SETTLED BEFORE THE APP IS MADE: `create` reads it. When it is not settled the person has
            # not been asked (or has not picked), so the definition goes back to ask, not on with a guess.
            if settle_platform(ctx) is None:
                return _finding(platform_question(ctx))
            svc = BlueprintService.create(output_dir=output_dir, app_id=Path(output_dir).name,
                                          name=ctx.app_name or "Application", domain="unknown",
                                          description=brief)
        if ctx.evidence:
            from services.blueprint import documents as documents_mod
            documents_mod.store(output_dir, list(ctx.evidence))
        already = completed_nodes(svc.doc, confirmed=nodes_recorded_done(output_dir) or None)
        plan = [k for k in domain_nodes() if k not in already]
        usage = RunUsage.for_app(svc)
        router = tiered_router(reasoning=ctx.reasoning)
        report = run(svc, make_executor(svc, router, usage=usage, reasoning=ctx.reasoning),
                     plan=plan, commit=True, user_request=brief,
                     app_root=str(Path(output_dir) / "app"),
                     observer_agent=anthropic_observer(router, usage=usage))
        if svc.doc.get("requirements") or svc.doc.get("pages"):
            brief_mod.advance_to_review(svc)
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith4] define_application failed")
        return _finding(f"The definition did not complete — {type(exc).__name__}: {exc}")
    failed = list(getattr(report, "failed", None) or [])
    doc = svc.doc
    # WHAT A DEFINITION IS AT THIS STEP: the requirements, and only them —
    # the first of the two reviews (see `services.smith.gates`). The modules,
    # screens and records are worked out from them once the person agrees.
    # Counting screens here read as "0 screens" on a definition that was
    # complete for its step (live, 2026-09-25).
    from services.smith import gates
    if doc.get("requirements"):
        gates.record_version(output_dir, gates.REQUIREMENTS, doc, request=brief)
    said = gates.say_requirements(doc)
    finding = (f"These parts of the definition did not complete: {', '.join(failed)}. "
               "The rest stands; say what to do about them.") if failed else ""
    return {"applied": True, "said": said, "finding": finding,
            "touched": [".forge/blueprint/current.json"], "version": int(doc.get("version") or 0)}


def _finding(text: str) -> dict:
    return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}


def _truthy(value: object, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "no", "0", "off")


def use_template(ctx: Ctx, args: dict) -> dict:
    """Start this application from the template it was made from.

    `exact` makes the template's definition this project's, as it stands, and
    leaves it at the product-model review: building it is the person's click,
    and that build authors nothing (see `project_templates`). `adapt` writes a
    NEW definition from what the person says is different, the template given
    to the agents as a reference document — the same definition run a brief
    gets, so it stops at the requirements review like any new application."""
    from services import project_templates as templates

    src = templates.pending(ctx.out)
    if not src:
        used = templates.source_of(ctx.out)
        if used:
            return _finding(f"The template “{used.get('name')}” was already used for this "
                            f"project ({used.get('mode') or used.get('status')}); it cannot be "
                            "used twice. Work with the application as it is now.")
        return _finding("This project was not started from a template. Define it from what "
                        "the person said instead (`define_application`).")
    mode = str(args.get("mode") or "").strip().lower()
    if mode not in (templates.MODE_EXACT, templates.MODE_ADAPT):
        return _finding("Which way: the exact same app, or something like it but different? "
                        "Ask them with those two choices; do not pick for them.")
    try:
        if mode == templates.MODE_EXACT:
            out = templates.use_exact(ctx.out, app_name=ctx.app_name or "")
            facts = out["summary"]
            held = templates.counted(facts["counts"])
            copied = (f"This is now an exact copy of “{src.get('name')}”: "
                      + (held or "its whole definition") + ". ")
            if out.get("complete", True):
                left = out.get("authoring_left") or []
                said = copied + ("Nothing has been built yet — press Build app on the card to "
                                 "build it exactly as it is. ")
                said += ("Some of its screens were never written as code in the original, so "
                         "the build writes those; everything else comes from the template as "
                         "it is. " if "page_code" in left else
                         "Everything is already worked out, so the build only assembles it. "
                         if not left else "")
                said += "If you want anything changed first, say so."
            else:
                said = copied + ("The template was saved before its screens and records were "
                                 "worked out, so what is copied is its requirements. Review them "
                                 "on the card; once you approve, the rest is worked out from "
                                 "them as for any app.")
            return {"applied": True, "said": said, "finding": "",
                    "touched": [".forge/blueprint/current.json"],
                    "version": int(out["doc"].get("version") or 1)}
        changes = str(args.get("changes") or "").strip() or ctx.message.strip()
        prepared = templates.prepare_adapt(ctx.out, app_name=ctx.app_name or "",
                                           changes=changes,
                                           keep_look=_truthy(args.get("keep_look"), True))
    except templates.TemplateError as exc:
        return _finding(str(exc))
    except ValueError as exc:  # BlueprintInvalid — the template's definition does not hold together
        return _finding(f"The template's definition could not be used as it is ({str(exc)[:200]}). "
                        "Tell the person plainly and offer to build something like it instead.")
    from services.blueprint import documents as documents_mod
    documents_mod.store(ctx.out, [prepared["document"]["text"]])
    return define_application(ctx, {"brief": prepared["brief"]})


def run(ctx: Ctx, name: str, args: dict) -> Outcome:
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    if name == "open_decisions":
        return Outcome(status="read", said=open_decisions(ctx, args))
    if name in ("define_application", "use_template"):
        out = define_application(ctx, args) if name == "define_application" else use_template(ctx, args)
        return Outcome(status="resolved" if out["applied"] and not out["finding"] else "needs_user",
                       said=str(out["said"]), touched=list(out["touched"]), finding=str(out["finding"]))
    raise KeyError(name)


__all__ = ["MAX_CLARIFY_TURNS", "brief_of", "define_application", "open_decisions", "run",
           "use_template"]
