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


def open_decisions(ctx: Ctx, args: dict) -> str:
    """The decisions the brief so far leaves open, as questions with chips.

    Silence is the default: a brief that says what the application is for and
    what people do in it gets no question. The cap is structural — past it,
    the answer is "define with what is known"."""
    from services.smith.clarify_brief import clarify_brief, company_palette_option
    from services.smith.figma_connect import find_in as figma_in
    from services.smith.uxpilot_connect import find_in as uxpilot_in

    brief = brief_of(ctx)
    if not brief.strip():
        return "Nothing has been asked for yet. There is no brief to clarify."
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

    brief = str(args.get("brief") or "").strip() or brief_of(ctx)
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
    # WHAT A DEFINITION IS AT THIS STEP. The domain nodes author the
    # requirements and the product's capabilities — the two everything else
    # reads; the screens, records and processes are planned from them after
    # the person approves. Counting screens here read as "0 screens" on a
    # definition that was complete for its step (live, 2026-09-25).
    reqs = [r for r in doc.get("requirements") or [] if isinstance(r, dict)]
    caps = [str(c.get("name") or "").strip() for c in (doc.get("product") or {}).get("capabilities") or []
            if isinstance(c, dict) and str(c.get("name") or "").strip()]
    name = str((doc.get("application") or {}).get("name") or ctx.app_name or "the application")
    said = (f"Defined what **{name}** is: {len(reqs)} requirement(s)"
            + (f" and {len(caps)} capabilit{'y' if len(caps) == 1 else 'ies'} — {', '.join(caps[:8])}"
               + (", …" if len(caps) > 8 else "") if caps else "")
            + ". It is ready to review. On approval the screens, records and processes are "
              "planned from it; nothing is built until then.")
    finding = (f"These parts of the definition did not complete: {', '.join(failed)}. "
               "The rest stands; say what to do about them.") if failed else ""
    return {"applied": True, "said": said, "finding": finding,
            "touched": [".forge/blueprint/current.json"], "version": int(doc.get("version") or 0)}


def _finding(text: str) -> dict:
    return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}


def run(ctx: Ctx, name: str, args: dict) -> Outcome:
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    if name == "open_decisions":
        return Outcome(status="read", said=open_decisions(ctx, args))
    if name == "define_application":
        out = define_application(ctx, args)
        return Outcome(status="resolved" if out["applied"] and not out["finding"] else "needs_user",
                       said=str(out["said"]), touched=list(out["touched"]), finding=str(out["finding"]))
    raise KeyError(name)


__all__ = ["MAX_CLARIFY_TURNS", "brief_of", "define_application", "open_decisions", "run"]
