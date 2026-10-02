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
import re
from typing import Any, Callable

from services.smith import loop as loop_mod
from services.smith import plan as plan_mod
from services.smith import reads, tools, trials, writes
from services.smith.loop import Observation
from services.smith.verbs import missing_fields
from services.smith4.context import opening
from services.smith4.outcome import Outcome
from services.smith4.verbs import Ctx, perform

logger = logging.getLogger(__name__)

#: (ask, page, observations, history) -> {tool, args, why}
Choose = Callable[[str, str, list, list], dict]

LOOK_FIRST = ("Nothing has been read this turn. Read the page (`read_page_code`, "
              "`grep`, `read_section`) or its data (`read_rows`) — the application "
              "usually answers this. "
              "Ask again only if it still stands.")

#: `done` with nothing changed and nothing tried. "Nothing needed doing" was
#: the reply to a category that could not be added, twice, after twelve steps
#: of reading code that read correctly (F&B, 2026-10-01): the fault was in
#: what the code DID, and only running it shows that.
NOTHING_TRIED = ("Nothing has changed this turn and nothing was tried. If they said "
                 "something does not work, try it (`try_workflow`, `try_request`, "
                 "`open_page`) and see what it does before deciding nothing needs "
                 "doing. If nothing does need doing, end with `answer` and say why.")
#: The start of the message when a trial that failed has not been tried
#: again since the change meant to fix it.
UNPROVEN = "Not shown to work yet:"
#: What a turn that ran out of steps, having changed nothing, is told.
OUT_OF_STEPS = ("You have run out of steps for this turn and nothing has been changed. End NOW "
                "with `answer`: in the person's words, what you found so far — what the tries "
                "showed, what works and what does not — and what is left to do. Do not say "
                "anything was changed. No other tool will run.")
#: How a seam says a control it made leads nowhere yet (`frame_change`).
UNWIRED = "Not working yet:"
#: What `done` hears when that control has not been tried since.
TRY_WIRED = ("Not tried yet. A control was found leading nowhere and has been changed since: "
             "try it now (`open_page` the screen it leads to, with what it sends) and see it "
             "work before ending.")
#: What a question or a plan hears on a turn the platform started.
NOBODY_TO_ASK = ("Nobody can answer: this turn was started by the build, not a person. Decide from "
                 "the definition — what the requirements, pages and workflows say — and act. "
                 "Several changes are made one after another in this turn, not proposed.")
#: The start of the message when the try after the change still fails.
STILL_FAILING = "Still not working:"


def turn(ctx: Ctx, *, choose: Choose, history: list | None = None,
         max_steps: int | None = None) -> Outcome:
    """One turn. `max_steps` overrides `loop.MAX_STEPS` for a caller with its
    own budget — a fault dispatched by the journey verifier gets a few steps,
    a person's ask gets the full cap."""
    observations: list[Observation] = []
    bench = trials.Bench(ctx.out)
    try:
        out = _run(ctx, choose, list(history or []), observations,
                   max_steps or loop_mod.MAX_STEPS, bench)
    finally:
        bench.close()
    out.steps = [o.tool for o in observations]
    return out


def _trial_key(o: Observation) -> str:
    a = o.args or {}
    return "|".join([o.tool, str(a.get("workflow") or a.get("path") or a.get("route") or ""),
                     str(a.get("method") or ""), str(a.get("as") or "").lower()])


def _changed_after(observations: list[Observation], i: int) -> bool:
    """Whether anything landed after step `i`. A rewrite that reports no file
    is still a change: Smith rewrote F&B's Orders page to fix what its try
    showed, and every try after was refused as "nothing has changed since" —
    five steps lost to not being allowed to look at its own fix (2026-10-02)."""
    return any(o.touched or (o.status == "resolved" and not tools.is_read(o.tool)
                             and not tools.is_trial(o.tool))
               for o in observations[i + 1:])


def _still_failing(observations: list[Observation]) -> list[str]:
    """Trials whose latest run came after a change and still failed — the
    change did not fix what it was for."""
    changes = [j for j, x in enumerate(observations) if x.touched]
    if not changes:
        return []
    latest: dict[str, int] = {}
    for i, o in enumerate(observations):
        if tools.is_trial(o.tool):
            latest[_trial_key(o)] = i
    out = []
    for i in sorted(latest.values()):
        o = observations[i]
        if i > changes[0] and trials.failed(o.said or ""):
            out.append(o.line().split(" ->", 1)[0].lstrip("- "))
    return out


def _unproven(observations: list[Observation]) -> str:
    """The trials that failed, were followed by a change, and have not been
    run since. A change made after a failing try is a guess until the try
    passes — the loop's oracle is the app itself."""
    still = _still_failing(observations)
    if still:
        return (f"{STILL_FAILING} {', '.join(still)} was tried again after the change and "
                "still fails. The change did not fix it. Read what the try reported — each "
                "step's output shows what the next step received — and change what it points "
                "at, then try again. If it cannot be fixed, end with `answer` and say what "
                "still fails and why.")
    open_: list[str] = []
    for i, o in enumerate(observations):
        if not tools.is_trial(o.tool) or not trials.failed(o.said or ""):
            continue
        if not _changed_after(observations, i):
            continue
        last_change = max(j for j, x in enumerate(observations) if x.touched)
        key = _trial_key(o)
        if any(_trial_key(x) == key for x in observations[last_change + 1:] if tools.is_trial(x.tool)):
            continue
        shown = o.line().split(" ->", 1)[0].lstrip("- ")
        if shown not in open_:
            open_.append(shown)
    if not open_:
        return ""
    return (f"{UNPROVEN} {', '.join(open_)} failed before the change and has not been tried "
            "since. Try it again now to show the change works — or, if it cannot be shown, "
            "end with `answer` and say so.")


def _before_done(observations: list[Observation], landed: list[str]) -> str:
    """What `done` must hear first, once each: nothing tried, or not shown to work."""
    said = {o.said.split(":", 1)[0] for o in observations if o.status == "error" and o.tool == "done"}
    if not landed and not any(tools.is_trial(o.tool) for o in observations) \
            and NOTHING_TRIED.split(":", 1)[0] not in said:
        return NOTHING_TRIED
    nudge = _unproven(observations)
    if nudge and nudge.split(":", 1)[0] not in said:
        return nudge
    # A CHANGE AN ORACLE CALLED UNWIRED IS TRIED ONCE WIRED. The search box's
    # screen was rewritten to read the query and the turn ended there, the
    # search never run (F&B replay, 2026-10-01).
    unwired = [i for i, o in enumerate(observations) if (o.said or "").startswith(UNWIRED)]
    if unwired and not any(tools.is_trial(o.tool) for o in observations[unwired[-1] + 1:]) \
            and TRY_WIRED.split(".", 1)[0] not in said:
        return TRY_WIRED
    return ""


def _failing_note(observations: list[Observation]) -> str:
    """Said after what landed when a turn ends with a try still failing: a
    change is reported, and so is that it did not fix what it was for."""
    still = _still_failing(observations)
    if not still:
        return ""
    return ("\n\nIt still does not work: I tried it again after the change and it failed "
            "the same way. Say “carry on” and I will keep at it.")


def standing_faults(doc: dict | None) -> list[str]:
    """Faults the platform's own checks see in a built application: a page
    handed something it never reads, pages of one module disagreeing on who
    may open them. Best-effort — a check that cannot run says nothing."""
    if not doc:
        return []
    out: list[str] = []
    try:
        from services.blueprint.functional_completeness import handoff_findings
        out += [f["detail"] for f in handoff_findings(doc)]
    except Exception:  # noqa: BLE001
        logger.debug("[smith] handoff check failed", exc_info=True)
    try:
        from services.blueprint.agent_contract import access_findings
        out += access_findings([p for p in doc.get("pages") or [] if isinstance(p, dict)
                                and str(p.get("status") or "").upper() != "REMOVED"])
    except Exception:  # noqa: BLE001
        logger.debug("[smith] access check failed", exc_info=True)
    # A page written before the page writer refused it: F&B's sign-in page
    # sent everyone to fixed addresses through next-auth (2026-10-02).
    routes = {str(p.get("id")): str(p.get("route") or p.get("id")) for p in doc.get("pages") or []
              if isinstance(p, dict)}
    for row in doc.get("pageCode") or []:
        if isinstance(row, dict) and re.search(r"""from\s+["']next-auth""",
                                                str(row.get("load") or "") + str(row.get("view") or "")):
            out.append(f"{routes.get(str(row.get('page')), row.get('page'))} signs people in through "
                       "next-auth itself, so it decides where each person lands instead of their role "
                       "— rewrite it with SignInForm/useSignIn (or SignUpForm/useSignUp) from @/sdk/client.")
    return out


def _run(ctx: Ctx, choose: Choose, history: list, observations: list[Observation],
         max_steps: int, bench: "trials.Bench | None" = None) -> Outcome:
    bench = bench or trials.Bench(ctx.out)
    if ctx.engine_refreshed and not observations:
        # SAID, SO A PASSING TRY IS BELIEVED. F&B's duplicate check passed on
        # the first try once the engine was current; not knowing why, the
        # loop spent eleven more steps looking for the bug the person had
        # reported and changed a workflow that was already right.
        shown = ", ".join(ctx.engine_refreshed[:8]) + (" …" if len(ctx.engine_refreshed) > 8 else "")
        observations.append(Observation(tool="refresh_engine", status="read", said=(
            f"Before this turn the application was out of date with the platform and was written "
            f"out again from its definition on the current one ({len(ctx.engine_refreshed)} "
            f"file(s): {shown}). A fault they reported may already be fixed by that: try it before "
            "changing anything, and if the try passes, say it works now and why.")))
    faults = standing_faults(ctx.doc()) if not observations else []
    if faults:
        # WHAT THE PLATFORM ALREADY KNOWS IS WRONG, SAID BEFORE ANYTHING ELSE.
        # F&B's order page dropped the basket the menu handed it, and its
        # order queue opened to any signed-in customer; the checks that see
        # both ran only when a page was written, so an app built before them
        # carried them until somebody tripped over each (fxa532bj, 2026-10-02).
        observations.append(Observation(tool="standing_faults", status="read", said=(
            "The platform's checks find these faults in the application as it stands:\n- "
            + "\n- ".join(faults[:8])
            + "\nFix any that bear on what they asked as part of this turn, and try the fix. "
              "Leave the rest unchanged and name them in your answer as found, not fixed.")))
    landed: list[str] = []
    touched: list[str] = []
    last: Outcome | None = None

    import time as _time
    turn_started = _time.monotonic()
    for _step in range(1, max_steps + 1):
        from services.smith4.definition import brief_of
        t0 = _time.monotonic()
        page = opening(ctx.project_id, ctx.out, ctx.ask, brief=brief_of(ctx))
        t1 = _time.monotonic()
        chosen = choose(ctx.ask, page, observations, history) or {}
        t2 = _time.monotonic()
        tool = str(chosen.get("tool") or "").strip()
        # WHERE A TURN'S TIME GOES, ONE LINE A STEP. Turns ran seven to ten
        # minutes with nothing saying whether the model, the page, or the step
        # itself was slow (Test2, 2026-09-28).
        logger.info("[smith-step] %d %s: page %.1fs (%d chars), choose %.1fs, seen %d chars, at %.0fs",
                    _step, tool or "-", t1 - t0, len(page), t2 - t1,
                    sum(len(o.said or "") for o in observations), t2 - turn_started)
        args = chosen.get("args") if isinstance(chosen.get("args"), dict) else {}
        args = {k: v for k, v in args.items() if v not in (None, "")}

        if ctx.unattended and tool in ("ask_user", "propose_plan"):
            observations.append(Observation(tool=tool, args=args, status="error", said=NOBODY_TO_ASK))
            continue
        if tool == "ask_user" and not any(o.status == "read" for o in observations) \
                and not any(o.said == LOOK_FIRST for o in observations):
            observations.append(Observation(tool=tool, args=args, status="error", said=LOOK_FIRST))
            continue
        if tool == "propose_plan":
            return _plan(ctx, args, landed, touched)
        # A QUESTION WITH NO WORDS IS NOT A QUESTION. `ask_user {}` ended a live
        # turn with "Nothing needed doing" — the model meant to ask and sent
        # nothing to ask. An error it can see, not a silent end.
        if tool == "ask_user" and not str(args.get("question") or "").strip():
            observations.append(Observation(tool=tool, args=args, status="error",
                                            said="`ask_user` needs `question`. Say what you are asking, or end another way."))
            continue
        if tool == "answer" and not str(args.get("text") or "").strip():
            observations.append(Observation(tool=tool, args=args, status="error",
                                            said="`answer` needs `text`. Say it, or end with `done`."))
            continue
        if tool == "done":
            first = _before_done(observations, landed)
            if first:
                observations.append(Observation(tool=tool, args=args, status="error", said=first))
                continue
        if tool in tools.TERMINAL_NAMES or not tool:
            ended = _ended(tool, args, landed, touched, last)
            if tool != "answer" and ended.status not in ("asked",):
                ended.said += _failing_note(observations)
            return ended
        if not tools.is_tool(tool):
            observations.append(Observation(tool=tool, args=args, status="error", said=tools.unknown(tool)))
            continue
        if tools.is_trial(tool):
            # THE SAME TRY AFTER A CHANGE IS A NEW TRY. Trying the workflow
            # again once the fix landed is the whole point; trying it twice
            # with nothing changed between is not reading the first answer.
            same = [i for i, o in enumerate(observations) if tools.is_trial(o.tool)
                    and loop_mod._identity(o.tool, o.args) == loop_mod._identity(tool, args)]
            if same and not _changed_after(observations, same[-1]):
                observations.append(Observation(
                    tool=tool, args=args, status="error",
                    said="That exact try has already been made and nothing has changed since — "
                         "read what it reported rather than repeating it."))
                continue
            seen = trials.run(tool, args, bench=bench, doc=ctx.doc())
            logger.info("[smith-try] %s %s -> %s", tool, args, " | ".join(seen.splitlines()[:6])[:600])
            observations.append(Observation(tool=tool, args=args, status="read", said=seen))
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

        if tools.is_definition(tool):
            from services.smith4 import definition as definition_mod
            step = definition_mod.run(ctx, tool, args)
            if step.status == "read":
                observations.append(Observation(tool=tool, args=args, status="read", said=step.said))
                continue
            observations.append(Observation(
                tool=tool, args=args, status="finding" if step.finding else step.status,
                said=step.finding or step.said, touched=list(step.touched)))
            if step.said and not step.finding:
                landed.append(step.said)
                if step.touched and step.status == "resolved":
                    ctx.applied.append(step.said)
            touched += [p for p in step.touched if p not in touched]
            last = step
            if not step.done and not step.finding:
                return _finished(landed, touched, step)
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
                # A GAP THE APPLICATION CAN LIST IS THE PERSON'S TO CHOOSE. "Which
                # record?" with the records as chips is a click; the model
                # guessing one is a guess. A gap with no known answers goes back
                # to the model, which may know it or may ask.
                from services.smith.slot_options import ask_for
                question, choices = ask_for(gaps, ctx.doc(), understanding)
                if choices:
                    return _finished(landed, touched, Outcome(status="asked", said=question,
                                                              options=choices))
                observations.append(Observation(
                    tool=tool, args=args, status="error",
                    said=(f"`{tool}` needs {', '.join(gaps)}, and the call did not carry them "
                          "and neither the message nor the application supplied them. Call it "
                          f"again with them, or ask. Ask: {question}")))
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
        logger.info("[smith-obs] %s %s -> %s: %s", tool, {k: str(v)[:80] for k, v in args.items()},
                    observations[-1].status, " ".join((observations[-1].said or "").split())[:400])
        if step.said and (not step.finding or (step.touched and step.said != step.finding)):
            # PART OF IT LANDED: twelve screens laid out again and one refused
            # is twelve screens changed — said, beside the one the loop is
            # told about.
            landed.append(step.said)
            if step.touched and step.status == "resolved":
                ctx.applied.append(step.said)
        touched += [p for p in step.touched if p not in touched]
        last = step
        if bench.running and any("/db/" in p or p.startswith("db/") for p in step.touched):
            # The copy was taken before the data model changed.
            bench.reset()
        if not step.done and not step.finding:
            return _finished(landed, touched, step)

    if not landed:
        # NOT "Nothing needed doing" AND "I stopped" IN ONE BREATH (F&B, twice):
        # a turn that ran out of steps while looking has not decided anything
        # — but it has FOUND things, and "I have not changed anything yet"
        # threw away that the admin's landing now worked (F&B replay). A turn
        # that changed nothing may speak, so it is asked once to say what it
        # found; it cannot take another step.
        said = ""
        try:
            observations.append(Observation(tool="done", status="error", said=OUT_OF_STEPS))
            final = choose(ctx.ask, opening(ctx.project_id, ctx.out, ctx.ask), observations, history) or {}
            if str(final.get("tool") or "") == "answer":
                said = str((final.get("args") or {}).get("text") or "").strip()
        except Exception:  # noqa: BLE001 — the fallback below is still true
            logger.warning("smith4: the out-of-steps answer could not be had", exc_info=True)
        if not said:
            last = next((o for o in reversed(observations) if o.status == "finding" and o.said), None)
            if last is not None:
                said = f"The last thing I tried did not work: {' '.join(last.said.split())[:600]}"
        tail = (f"\n\nThis turn ran out of steps ({max_steps}) before I changed anything. "
                "Say “carry on” and I will pick up from there.")
        return Outcome(status="no_op", touched=list(touched), said=(said + tail) if said else (
            f"I have not changed anything yet — this turn ran out of steps ({max_steps}) "
            "while I was still looking into it. Say “carry on” and I will pick up from there."))
    failing = _failing_note(observations)
    if not failing and _unproven(observations).startswith(UNPROVEN):
        # The change landed on the last step the cap allowed, untried.
        failing = ("\n\nI have not yet tried it again since the change, so I cannot say it works "
                   "yet — this turn ran out of steps. Say “carry on” and I will try it.")
    note = failing or loop_mod.remaining_note(observations, capped=True).replace(
        f"{loop_mod.MAX_STEPS} steps", f"{max_steps} steps")
    return _finished(landed, touched, last, note=note)


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
    # A STEP ALREADY WAITING IS NOT A NEW STEP. Copied into the new plan it
    # took a place the person's own ask needed (SnapIT replay: five old steps
    # and the screens rebuild pushed past the cap).
    def _norm(x: str) -> str:
        return " ".join(str(x).split()).lower()
    waiting = {_norm(w) for w in plan_mod.peek(ctx.out)}
    steps = [str(s).strip() for s in (args.get("steps") or [])
             if str(s).strip() and _norm(s) not in waiting]
    if len(steps) < 2:
        return _finished(landed, touched, Outcome(status="asked", said=(
            "I could not tell the parts of that apart. Say the first thing you want and I "
            "will start there.")))
    key = " | ".join(steps)
    if confirm.granted(ctx.out, ctx.message, "plan", key):
        return _finished(landed, touched, Outcome(status="asked", said=plan_mod.as_question(steps, [])))
    confirm.remember(ctx.out, confirm.fingerprint("plan", key))
    planned, over = plan_mod.split(steps)
    # A STEP THAT SPLITS KEEPS THE PLAN IT IS PART OF. Its sub-steps go in
    # front of what was still to do; replacing the plan lost "show the area"
    # and "take the current location" after "next" split the step before
    # them (UAT jubyt8jk).
    rest = [r for r in plan_mod.peek(ctx.out) if r not in planned]
    if rest:
        plan_mod.remember_all(ctx.out, planned + over + rest)
        question = plan_mod.as_question(planned, []).replace(
            "\n\nShall I work through them?",
            "\n\nAfter those, the rest of the plan is still waiting:\n"
            + "\n".join(f"- {a}" for a in over + rest) + "\n\nShall I work through them?")
        return Outcome(status="asked", said=question,
                       options=[plan_mod.ALL_LABEL, plan_mod.FIRST_LABEL, plan_mod.REWORD_LABEL],
                       touched=list(touched))
    plan_mod.remember(ctx.out, planned, agreed=False)
    return Outcome(status="asked", said=plan_mod.as_question(planned, over),
                   options=[plan_mod.ALL_LABEL, plan_mod.FIRST_LABEL, plan_mod.REWORD_LABEL],
                   touched=list(touched))


def _ended(tool: str, args: dict, landed: list[str], touched: list[str],
           last: Outcome | None) -> Outcome:
    if tool == "ask_user":
        question = str(args.get("question") or "").strip()
        options = [str(o).strip() for o in (args.get("options") or []) if str(o).strip()]
        if question:
            return Outcome(status="asked", said=question, options=options, touched=list(touched))
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
    if last.finding and last.finding != last.said:
        # WHAT WAS NOT DONE IS SAID BESIDE WHAT WAS. Ten screens laid out
        # again and /profile refused was reported as the ten alone (SnapIT
        # replay, 2026-10-01).
        said.append("Not done: " + last.finding)
    answer = "\n\n".join(dict.fromkeys(s for s in said if s)) or last.said
    return Outcome(status=last.status, said=answer + note, options=list(last.options),
                   diff_summary=last.diff_summary, touched=list(touched), finding=last.finding)


__all__ = ["turn", "Choose", "LOOK_FIRST", "NOTHING_TRIED", "UNPROVEN", "STILL_FAILING"]
