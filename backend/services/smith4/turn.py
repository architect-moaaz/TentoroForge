"""One turn: act, observe, act — from the first step.

There is no call before the loop. The model is shown the ask, the exchange, a
first page of the application and the catalogue, and chooses: a read, a
write, a verb, or one of the ways a turn ends. What it chose is carried out
and what happened is the next observation. The rules that bound it are
structural, not a policy about content:

* a name outside the catalogue is an error the model sees, never the nearest
  verb (`turn.py`'s rule from the Blueprint Smith, kept);
* the same call twice is refused by identity (`loop.already_done`);
* a verb without the fields it declares is told which, after the message and
  the document have been tried for them (`slot_options.fill_from`);
* a question with nothing read is sent to look, once — measured live, "does
  the section exist?" was asked with the answer on line 211;
* what an oracle PROVES is a finding and the loop carries on; a question for
  the person ends the turn;
* `MAX_STEPS`, and what the cap cuts off is said.

The reply is assembled from what the seams reported, never from a summary the
model writes at the end — that is a chance to describe a change that did not
happen. `answer` may speak only in a turn that changed nothing.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from services.smith import loop as loop_mod
from services.smith import plan as plan_mod
from services.smith import reads, tools, writes
from services.smith.loop import Observation
from services.smith.verbs import missing_fields
from services.smith4.context import opening
from services.smith4.outcome import Outcome
from services.smith4.verbs import Ctx, perform

logger = logging.getLogger(__name__)

#: (ask, page, observations, history) -> {tool, args, why}
Choose = Callable[[str, str, list, list], dict]

LOOK_FIRST = ("Nothing has been read this turn. Read the page (`read_page_code`, "
              "`grep`, `read_section`) — the application usually answers this. "
              "Ask again only if it still stands.")


def turn(ctx: Ctx, *, choose: Choose, history: list | None = None) -> Outcome:
    observations: list[Observation] = []
    landed: list[str] = []
    touched: list[str] = []
    last: Outcome | None = None
    history = list(history or [])

    for _step in range(1, loop_mod.MAX_STEPS + 1):
        page = opening(ctx.project_id, ctx.out, ctx.ask)
        chosen = choose(ctx.ask, page, observations, history) or {}
        tool = str(chosen.get("tool") or "").strip()
        args = chosen.get("args") if isinstance(chosen.get("args"), dict) else {}
        args = {k: v for k, v in args.items() if v not in (None, "")}

        if tool == "ask_user" and not any(o.status == "read" for o in observations) \
                and not any(o.said == LOOK_FIRST for o in observations):
            observations.append(Observation(tool=tool, args=args, status="error", said=LOOK_FIRST))
            continue
        if tool == "propose_plan":
            return _plan(ctx, args, landed, touched)
        if tool in tools.TERMINAL_NAMES or not tool:
            return _ended(tool, args, landed, touched, last)
        if not tools.is_tool(tool):
            observations.append(Observation(tool=tool, args=args, status="error", said=tools.unknown(tool)))
            continue
        if loop_mod.already_done(tool, args, observations):
            observations.append(Observation(
                tool=tool, args=args, status="error",
                said="That exact step has already been taken this turn — read what it "
                     "reported rather than repeating it."))
            continue

        if tools.is_read(tool):
            seen = reads.run(tool, args, output_dir=ctx.out, doc=ctx.doc())
            observations.append(Observation(tool=tool, args=args, status="read", said=seen))
            continue

        if tools.is_write(tool):
            out = writes.run(tool, args, output_dir=ctx.out, reasoning=ctx.reasoning)
            step = Outcome(status="resolved" if out.get("applied") and not out.get("finding") else "needs_user",
                           said=str(out.get("said") or ""), touched=list(out.get("touched") or []),
                           finding=str(out.get("finding") or ""))
        else:
            understanding = _understanding_for(ctx, tool, args)
            gaps = missing_fields(understanding)
            if gaps:
                observations.append(Observation(
                    tool=tool, args=args, status="error",
                    said=(f"`{tool}` needs {', '.join(gaps)}, and the call did not carry them "
                          "and neither the message nor the application supplied them. Call it "
                          "again with them, or ask.")))
                continue
            try:
                step = perform(ctx, tool, understanding)
            except Exception as exc:  # noqa: BLE001 — a step degrades, the turn does not crash
                logger.exception("smith4: %s failed", tool)
                step = Outcome(status="needs_user", said=f"`{tool}` failed: {type(exc).__name__}: {exc}",
                               finding=f"`{tool}` raised {type(exc).__name__}: {exc}")

        observations.append(Observation(
            tool=tool, args=args, status="finding" if step.finding else step.status,
            said=step.finding or step.said, touched=list(step.touched)))
        if step.said and not step.finding:
            landed.append(step.said)
        touched += [p for p in step.touched if p not in touched]
        last = step
        if not step.done and not step.finding:
            return _finished(landed, touched, step)

    return _finished(landed, touched, last, note=loop_mod.remaining_note(observations, capped=True))


def _understanding_for(ctx: Ctx, verb: str, args: dict) -> dict:
    """A tool call as the understanding every seam reads: the full shape, the
    two names for a screen reconciled, and the gaps tried against the message
    and the document before anyone is asked for them."""
    from services.smith.slot_options import fill_from
    from services.smith.understand_ask import _blank, _env_name_only, _is_route

    u = _blank(verb=verb, **args)
    for key in ("token_env", "key_env"):
        if u.get(key):
            u[key] = _env_name_only(u[key])
    route, target = str(u.get("route") or "").strip(), str(u.get("target_file") or "").strip()
    if not route and _is_route(target):
        u["route"] = target
    if not target and route:
        u["target_file"] = route
    gaps = missing_fields(u)
    if gaps:
        known = fill_from(gaps, ctx.ask, ctx.doc(), u)
        if known:
            u.update(known)
    return u


def _plan(ctx: Ctx, args: dict, landed: list[str], touched: list[str]) -> Outcome:
    """Several asks, shown as a plan and agreed to once. Nothing is done before
    the yes — starting on step one while showing the list is the old silence
    with a receipt. The yes is fingerprinted so it is not re-planned."""
    from services.smith import confirm
    steps = [str(s).strip() for s in (args.get("steps") or []) if str(s).strip()]
    if len(steps) < 2:
        return _finished(landed, touched, Outcome(status="asked", said=(
            "I could not tell the parts of that apart. Say the first thing you want and I "
            "will start there.")))
    key = " | ".join(steps)
    if confirm.granted(ctx.out, ctx.message, "plan", key):
        return _finished(landed, touched, Outcome(status="asked", said=plan_mod.as_question(steps, [])))
    confirm.remember(ctx.out, confirm.fingerprint("plan", key))
    planned, over = plan_mod.split(steps)
    plan_mod.remember(ctx.out, planned)
    return Outcome(status="asked", said=plan_mod.as_question(planned, over),
                   options=[plan_mod.ALL_LABEL, plan_mod.FIRST_LABEL, plan_mod.REWORD_LABEL],
                   touched=list(touched))


def _ended(tool: str, args: dict, landed: list[str], touched: list[str],
           last: Outcome | None) -> Outcome:
    if tool == "ask_user":
        question = str(args.get("question") or "").strip()
        if question:
            return Outcome(status="asked", said=question, touched=list(touched))
    if tool == "answer" and not landed:
        said = str(args.get("text") or "").strip()
        if said:
            return _finished([said], touched, Outcome(status="no_op", said=said))
    return _finished(landed, touched, last)


def _finished(landed: list[str], touched: list[str], last: Outcome | None, *,
              note: str = "") -> Outcome:
    """The turn's reply, from what the steps reported. An unsettled finding is
    added back after what landed, so a turn that ends on one does not say
    "Done" and report `needs_user` in the same breath."""
    last = last or Outcome(status="no_op", said="Nothing needed doing.")
    said = list(landed)
    if last.finding and last.said:
        said.append(last.said)
    answer = "\n\n".join(dict.fromkeys(s for s in said if s)) or last.said
    return Outcome(status=last.status, said=answer + note, options=list(last.options),
                   diff_summary=last.diff_summary, touched=list(touched), finding=last.finding)


__all__ = ["turn", "Choose", "LOOK_FIRST"]
