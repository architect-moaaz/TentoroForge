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

import os

import logging
import re
from typing import Any, Callable

from services.smith import loop as loop_mod
from services.smith import plan as plan_mod
from services.smith import reads, reported, tools, trials, web, writes
from services.smith.loop import Observation
from services.engineer.journal import Budget, Journal
from services.smith.verbs import missing_fields
from services.smith4.context import opening
from services.smith4.outcome import Outcome
from services.smith4.verbs import Ctx, perform

logger = logging.getLogger(__name__)

#: (ask, page, observations, history) -> {tool, args, why}
Choose = Callable[[str, str, list, list], dict]

#: How long a turn may run, in minutes. A turn had twenty steps and no
#: clock: 34 minutes on one request, then "ran out of steps" (E-commerce,
#: 2026-10-09). When the time is spent the turn ends with what it proved.
TURN_MINUTES = float(os.environ.get("FORGE_SMITH_TURN_MINUTES") or 20)

#: What a change hears when the person named the screen they were on and
#: nothing has been tried THROUGH that screen yet — a process run directly
#: proves nothing about the button they pressed.
REPRODUCE_AS_REPORTED = (
    "They saw this on {route} as {who}. Nothing has been tried through that screen yet: "
    "open it as them (`open_page` with `route` and `as`) and do what they did before changing "
    "anything. A process run directly (`try_workflow`) is not what they saw.")

def untried_as_reported(report: dict, tried: list) -> str:
    """When the person named the screen they were on and nothing has been
    tried THROUGH it, what the change is told; empty otherwise. `tried` are
    the turn's trial observations so far."""
    route = (report or {}).get("route")
    if not route or not tried or any(o.tool in reported.BROWSER_TRIALS for o in tried):
        return ""
    return REPRODUCE_AS_REPORTED.format(route=route, who=reported.who(report) or "them")


#: Words that mean: pick up the last turn where it stopped.
CARRY_ON = re.compile(r"^\s*(?:carry on|continue|go on|keep going|resume|proceed|pick (?:it )?up)\b", re.I)

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
#: What an `answer` hears, once, on a turn that has changed nothing. ToroCommerce
#: (forge-v3, 2026-10-07): asked why the admin could not add a variant, Smith
#: answered "I'll fix the page so the form sends the full product record — let
#: me rewrite that part of the view now", and that answer ended the turn: the
#: person waited for a change no step made. `answer` is how a turn speaks, not
#: how it acts; one look at what it is about to say decides which.
ANSWER_CHANGES_NOTHING = (
    "Nothing has been changed this turn, and `answer` changes nothing — it ends the turn. "
    "If what you are about to say is that something should be changed, make that change now "
    "and try it. If you have not seen the fault happen through the screen they used, open "
    "that screen (`open_page`) and use it first. If this is an answer — how to do something, "
    "why it already works, why it cannot be changed — send the same `answer` again.")
#: What the first direct edit of a turn hears when nothing has been tried. The
#: variant form Smith "fixed" on ToroCommerce was not broken: it read the code,
#: blamed a field it misread, and never pressed the button (2026-10-07).
REPRODUCE_FIRST = (
    "Nothing has been tried this turn. If they said something does not work, use it first — the "
    "screen they used, as them (`try_expectation` when a statement covers it, `open_page`, `try_workflow`, "
    "`try_request`) — so the change answers "
    "what happens, not what the code seems to say. If this IS the change they asked for (not a report "
    "that something is broken), call it again with `requested: true`.")
#: What an answer hears on a turn that has tried nothing.
ANSWER_UNTRIED_HEAD = "Nothing has been tried this turn"


def answer_untried(ask: str) -> str:
    said = " ".join(str(ask).split())[:300]
    return (f"{ANSWER_UNTRIED_HEAD}, and an answer says what the application does. They said: \u201c{said}\u201d. "
            "If that could be a report that something behaves wrongly — or a question about what it does — "
            "use it first: the screen it is about, as the person it is about (`open_page`, `try_workflow`), "
            "and answer from what it showed, or fix what it showed. Answer without trying only when it is "
            "not about what the application does (a plan, a cost, how to do something) — then send the "
            "answer again.")


#: The writes that change code or the definition directly: the first of them
#: in a turn that has tried nothing is asked to reproduce first. TCommerce's
#: empty bag (measured on a copy, 2026-10-07) went straight to rewriting
#: /cart through `write_page_code`, tried afterwards, and ran out of steps.
REPRODUCE_BEFORE = frozenset({"edit_file", "edit_definition", "write_page_code", "rewrite_pages",
                              "write_frame", "write_section", "set_field"})


#: What an edit to the platform's own files hears without a failing try.
PATCH_NEEDS_PROOF = (
    "That file is the platform's — the engine every application runs on. It is patched for this "
    "application only once a try in this turn has shown the fault it fixes, and the patch is kept only "
    "if a try after it passes. Try it first; if the try passes, the fault is not there.")
#: What `requested: true` hears when the person's words report a fault.
NOT_ASKED_FOR = (
    "Their words report that something does not work; they do not ask for this change. Use it first, as "
    "them, on the screen they used (`open_page`, `try_workflow`) and fix what the try shows.")
#: What a change hears in a turn a check started, before a try has shown the fault.
FAULT_NOT_SEEN = (
    "This turn was started by a check that saw a fault, and no try in it has shown that fault yet. Use "
    "what the check reported, as the person it names; if the try works, the fault is not there — end "
    "with `done` and say what the try showed. Change nothing for a fault you have not seen.")
#: A step these answered never ran: asking for it again is not a repeat.
_NOT_RUN = frozenset({REPRODUCE_FIRST, PATCH_NEEDS_PROOF, NOT_ASKED_FOR, FAULT_NOT_SEEN})


def _change_said(tool: str, args: dict) -> str:
    what = args.get("why") or args.get("brief") or args.get("replace") or ""
    where = args.get("path") or args.get("route") or args.get("section") or args.get("file") or ""
    return " ".join(f"{tool} {where}: {what}".split())[:400]


#: The question behind `requested: true`, asked of a small model on its own.
#: The acting model labelling its own change was no guard: TCommerce's "bag is
#: empty" was rewritten as a requested change (measured, 2026-10-08).
ASKED_FOR_MODEL = "claude-haiku-4-5-20251001"


def asked_for(words: str, change: str) -> bool:
    """Whether the person's words ask for `change` itself, rather than report
    that something does not work. False when it cannot be told — the safe side
    is to try first."""
    words = " ".join(str(words).split())[:1500]
    if not words or not change:
        return False
    try:
        from services.llm_client import complete
        verdict = complete(model=ASKED_FOR_MODEL, max_tokens=5, temperature=0, content=(
            f"A person wrote to the builder of their application:\n\"{words}\"\n\n"
            f"The builder wants to make this change: \"{change}\"\n\n"
            "Reply with one word. REQUEST if the person's words ask for this change itself. REPORT if "
            "they say something does not work as it should — a fault to find. OTHER otherwise."))
    except Exception:  # noqa: BLE001 — not knowing is not a yes
        logger.warning("smith4: the asked-for check could not run", exc_info=True)
        return False
    return str(verdict or "").strip().upper().startswith("REQUEST")
#: What `done` hears when the last change has not been used since.
TRY_AFTER = (
    "Changed, not yet tried. Use what you changed — as the person who asked, on the screen they use — "
    "and see it work before ending. If it cannot be tried, end with `answer` saying so.")
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
    # THE PERSON'S WORDS GO WITH EVERY BRIEF THIS TURN HANDS ON (`asked`).
    from services.smith.asked import ASKED
    asked = ctx.ask or ctx.message or ""
    if ctx.asked_from and ctx.asked_from not in asked:
        asked = f"{ctx.asked_from}\n(This turn does one part of it: {asked})"
    token = ASKED.set(asked)
    rtoken = reported.REPORTED.set(dict(ctx.report or {}))
    from services.smith import file_edit
    started = {p.get("id") for p in file_edit.load_patches(ctx.out)}
    journal = Journal(ctx.out)
    journal.write("turn:start", message=(ctx.message or ctx.ask or "")[:300], report=dict(ctx.report or {}),
                  unattended=ctx.unattended)
    try:
        out = _run(ctx, choose, list(history or []), observations,
                   max_steps or loop_mod.MAX_STEPS, bench, journal=journal)
    finally:
        reported.REPORTED.reset(rtoken)
        ASKED.reset(token)
        bench.close()
        try:
            journal.write("turn:end", status=getattr(out, "status", "crashed") if "out" in locals() else "crashed",
                          said=(getattr(out, "said", "") or "")[:400] if "out" in locals() else "",
                          steps=[o.tool for o in observations])
        except Exception:  # noqa: BLE001 — the journal never ends a turn
            logger.warning("smith4: could not journal the turn's end", exc_info=True)
    out.steps = [o.tool for o in observations]
    # A PLATFORM PATCH IS KEPT ONLY ON PROOF: a try after the last edit that
    # passed, and nothing that failed before still failing.
    pending = [p["id"] for p in file_edit.load_patches(ctx.out)
               if p.get("id") not in started and p.get("status") == "pending"]
    if pending:
        edits = [i for i, o in enumerate(observations) if o.tool == "edit_file" and _is_change(o)]
        after = [o for o in observations[(edits[-1] + 1 if edits else 0):] if tools.is_trial(o.tool)]
        proven = bool(after) and not trials.failed(after[-1].said or "") and not _still_failing(observations)
        said = file_edit.settle(ctx.out, pending, proven)
        if said:
            out.said = (out.said + "\n\n" if out.said else "") + " ".join(said)
    return out


def _trial_key(o: Observation) -> str:
    a = o.args or {}
    return "|".join([o.tool, str(a.get("workflow") or a.get("path") or a.get("route") or a.get("statement") or ""),
                     str(a.get("method") or ""), str(a.get("as") or "").lower()])


def _is_change(o: Observation) -> bool:
    """A step that changed the app. A rewrite that reports no file is still a
    change: Smith rewrote F&B's Orders page to fix what its try showed, and
    every try after was refused as "nothing has changed since" — five steps
    lost to not being allowed to look at its own fix (2026-10-02).

    ONE MEANING FOR EVERY CHECK. `_changed_after` counted such a rewrite and
    the checks after it counted only steps with files: a permissions rewrite
    (no file) after a failing try, then `done`, asked for the latest change
    with a file, found none, and the turn died on `max()` of nothing
    (ihf6pjga, 2026-10-05 18:52)."""
    return bool(o.touched) or (o.status == "resolved" and not tools.is_read(o.tool)
                               and not tools.is_trial(o.tool))


def _changed_after(observations: list[Observation], i: int) -> bool:
    """Whether anything landed after step `i`."""
    return any(_is_change(o) for o in observations[i + 1:])


def _broken_controls(said: str) -> set[str]:
    """The controls a page trial found not working: `button "Decrease quantity"`."""
    from services.blueprint.page_review import BROKEN_OUTCOMES
    found = set()
    for line in (said or "").splitlines():
        m = re.match(r'^\s+(\w+ "[^"]*"): (.*)$', line)
        if m and any(m.group(2).startswith(v) for v in BROKEN_OUTCOMES.values()):
            found.add(m.group(1))
    return found


def _failed_alike(before: str, after: str) -> bool:
    """Whether a try after a change failed the way it did before. A page fails
    by its controls: ToroCommerce's fixed minus button worked, its plus button
    answered 422, and the turn said "failed the same way" (measured on a copy,
    2026-10-07). Anything else fails as it did when both runs fail."""
    if not (trials.failed(before) and trials.failed(after)):
        return False
    if trials.EXPECTATION_HEAD.match(after.split("\n", 1)[0]):
        # A statement fails by its checks: the same check failing again is
        # "still", a different one is what the change broke or uncovered.
        seen = lambda s: {l.strip() for l in s.splitlines() if l.startswith("  - ")}  # noqa: E731
        return bool(seen(before) & seen(after))
    b, a = _broken_controls(before), _broken_controls(after)
    if b and a is not None:
        head = lambda s: s.split("\n", 1)[0]
        hard = re.search(r"HTTP ([45]\d\d)", head(after))
        return bool(b & a) or bool(hard and re.search(r"HTTP ([45]\d\d)", head(before)))
    return True


def _trial_runs(observations: list[Observation]) -> dict[str, list[int]]:
    runs: dict[str, list[int]] = {}
    for i, o in enumerate(observations):
        if tools.is_trial(o.tool):
            runs.setdefault(_trial_key(o), []).append(i)
    return runs


def _still_failing(observations: list[Observation]) -> list[str]:
    """Trials that failed before a change and, run again after it, failed the
    same way — the change did not fix what it was for."""
    changes = [j for j, x in enumerate(observations) if _is_change(x)]
    if not changes:
        return []
    out = []
    for idxs in _trial_runs(observations).values():
        last = idxs[-1]
        prior = [c for c in changes if c < last]
        before = [i for i in idxs if prior and i < prior[-1]]
        if before and _failed_alike(observations[before[-1]].said or "", observations[last].said or ""):
            out.append(observations[last].line().split(" ->", 1)[0].lstrip("- "))
    return out


def _new_failures(observations: list[Observation]) -> list[str]:
    """Trials run after a change that fail in a way they did not before it —
    found, not "still": said as what the try showed."""
    changes = [j for j, x in enumerate(observations) if _is_change(x)]
    if not changes:
        return []
    still = set(_still_failing(observations))
    out = []
    for idxs in _trial_runs(observations).values():
        last = idxs[-1]
        o = observations[last]
        name = o.line().split(" ->", 1)[0].lstrip("- ")
        if last > changes[0] and trials.failed(o.said or "") and name not in still:
            broken = sorted(_broken_controls(o.said or ""))
            out.append(name + (f" ({', '.join(broken)})" if broken else ""))
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
        last_change = max(j for j, x in enumerate(observations) if _is_change(x))
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
    # NO CLAIM WITHOUT PROOF. A change after which nothing was used is a
    # change the reply cannot say works.
    changes = [i for i, o in enumerate(observations) if _is_change(o)]
    tries = [i for i, o in enumerate(observations) if tools.is_trial(o.tool)]
    if landed and changes and (not tries or tries[-1] < changes[-1]) \
            and TRY_AFTER.split(",", 1)[0] not in said:
        return TRY_AFTER
    return ""


def _failing_note(observations: list[Observation]) -> str:
    """Said after what landed when a turn ends with a try still failing: a
    change is reported, and so is that it did not fix what it was for."""
    still = _still_failing(observations)
    if still:
        return ("\n\nIt still does not work: I tried it again after the change and it failed "
                "the same way. Say “carry on” and I will keep at it.")
    fresh = _new_failures(observations)
    if fresh:
        return ("\n\nAfter the change, this was tried and does not work: " + "; ".join(fresh[:4])
                + ". Say “carry on” and I will look at it.")
    return ""


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


def _last_turn_unfinished(journal: Journal) -> list[dict]:
    """The steps of the last turn when it did not finish — what "carry on"
    picks up from. Empty when it finished, or there was none."""
    rows = list(journal.rows())
    starts = [i for i, r in enumerate(rows) if r.get("event") == "turn:start"]
    if not starts:
        return []
    last = rows[starts[-1]:]
    end = next((r for r in last if r.get("event") == "turn:end"), None)
    if end is not None and str(end.get("status") or "") in ("resolved", "done", "asked"):
        return []
    return [r for r in last if r.get("event") == "turn:step"]


def _run(ctx: Ctx, choose: Choose, history: list, observations: list[Observation],
         max_steps: int, bench: "trials.Bench | None" = None, journal: Journal | None = None) -> Outcome:
    bench = bench or trials.Bench(ctx.out)
    journal = journal or Journal(ctx.out)
    # CARRY ON MEANS FROM WHERE IT STOPPED. "Carry on" started a fresh turn
    # whose only memory was six lines of chat (E-commerce, 2026-10-09); the
    # last turn's journal is what it picks up.
    if not observations and CARRY_ON.match(ctx.message or ""):
        steps = _last_turn_unfinished(journal)
        if steps:
            shown = "\n".join(f"- {r.get('tool')} ({r.get('status')}): {str(r.get('said') or '')[:160]}"
                              for r in steps[-12:])
            observations.append(Observation(tool="last_turn", status="read", said=(
                "The last turn stopped before it finished. What it did and found, in order:\n" + shown
                + "\nPick up from there: do not repeat what is known; try what was about to be tried.")))
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
    budget = Budget(TURN_MINUTES)
    out_of_time = False
    journaled = 0
    for _step in range(1, max_steps + 1):
        from services.smith4.definition import brief_of
        for o in observations[journaled:]:
            journal.write("turn:step", tool=o.tool, status=o.status, said=(o.said or "")[:300])
        journaled = len(observations)
        if budget.over():
            out_of_time = True
            break
        t0 = _time.monotonic()
        # WHO SAW IT, first: the person, the screen, the viewport the
        # problem was reported from (`services.smith.reported`).
        page = reported.block(ctx.report) + opening(ctx.project_id, ctx.out, ctx.ask, brief=brief_of(ctx))
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
        if chosen.get("unreachable"):
            # NOT "NOTHING NEEDED DOING". The model could not be reached (the
            # account's credit ran out mid-test, 2026-10-02) and the turn said
            # nothing needed doing — a false answer to "add a spice level".
            return _finished(landed, touched, Outcome(status="no_op", said=(
                "I could not reach my reasoning service just now, so I stopped here"
                + (" — what is above is done and kept." if landed else " and nothing was changed.")
                + " Please try again in a few minutes.")))
        if tool == "answer" and not landed:
            heard = [o.said or "" for o in observations if o.tool == "answer" and o.status == "error"]
            if not any(tools.is_trial(o.tool) for o in observations):
                # AN ANSWER ABOUT WHAT THE APP DOES COMES FROM USING IT. TCommerce's
                # tester reported inactive products showing; Smith answered "Yes,
                # that is exactly how it works" from the business rule, in two
                # steps, having tried nothing (measured on a copy, 2026-10-07).
                if not any(h.startswith(ANSWER_UNTRIED_HEAD) for h in heard):
                    observations.append(Observation(tool=tool, args=args, status="error",
                                                    said=answer_untried(ctx.ask or ctx.message or "")))
                    continue
            elif ANSWER_CHANGES_NOTHING not in heard:
                observations.append(Observation(tool=tool, args=args, status="error",
                                                said=ANSWER_CHANGES_NOTHING))
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
        if loop_mod.already_done(tool, args, [o for o in observations if o.said not in _NOT_RUN]):
            observations.append(Observation(
                tool=tool, args=args, status="error",
                said="That exact step has already been taken this turn — read what it "
                     "reported rather than repeating it."))
            continue

        if tools.is_read(tool):
            seen = reads.run(tool, args, output_dir=ctx.out, doc=ctx.doc())
            observations.append(Observation(tool=tool, args=args, status="read", said=seen))
            continue

        if tools.is_web(tool):
            seen = web.run(tool, args, said=web.person_said(ctx.ask, history), output_dir=ctx.out)
            logger.info("[smith-web] %s %s -> %s", tool, args, " | ".join(seen.splitlines()[:2])[:300])
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

        if tool in REPRODUCE_BEFORE:
            # NOT PAST THE RULE BY ASKING TWICE. TCommerce's empty bag was held
            # once, a second rewrite went through, and the shopper stopped being
            # sent to the cart — a change nobody asked for, the bag never tried
            # (measured on a copy, 2026-10-07). Until a try has run, a change
            # runs only when the call says it is the change they asked for.
            tried = [o for o in observations if tools.is_trial(o.tool)]
            if ctx.unattended:
                # A TURN A CHECK STARTED IS A FAULT TO SEE, NOT A REQUEST. Nobody
                # asked for anything, so `requested` means nothing here, and a
                # change needs a try in this turn that fails: ToroCommerce's
                # after-change check flagged the plus button's refusal and its
                # repair rewrote a working workflow (measured, 2026-10-08).
                if not any(trials.failed(o.said or "") for o in tried):
                    observations.append(Observation(tool=tool, args=args, status="error", said=FAULT_NOT_SEEN))
                    continue
            elif not tried or untried_as_reported(ctx.report, tried):
                claimed = str(args.get("requested") or "").strip().lower() in ("true", "1", "yes")
                if not claimed:
                    said = REPRODUCE_FIRST if not tried else untried_as_reported(ctx.report, tried)
                    observations.append(Observation(tool=tool, args=args, status="error", said=said))
                    continue
                if not asked_for(ctx.message or ctx.ask or "", _change_said(tool, args)):
                    observations.append(Observation(tool=tool, args=args, status="error", said=NOT_ASKED_FOR))
                    continue
            if tool == "edit_file":
                from services.smith import file_edit
                rel, _why = file_edit._app_rel(ctx.out, str(args.get("path") or ""))
                if rel and file_edit.classify(ctx.doc() or {}, rel)["kind"] == "platform" and not any(
                        tools.is_trial(o.tool) and trials.failed(o.said or "") for o in observations):
                    observations.append(Observation(tool=tool, args=args, status="error", said=PATCH_NEEDS_PROOF))
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
            for _ask in range(2):
                final = choose(ctx.ask, opening(ctx.project_id, ctx.out, ctx.ask), observations, history) or {}
                if str(final.get("tool") or "") == "answer":
                    said = str((final.get("args") or {}).get("text") or "").strip()
                    break
                # A STEP INSTEAD OF AN ANSWER IS ASKED FOR AGAIN, ONCE.
                observations.append(Observation(tool=str(final.get("tool") or "?"), status="error", said=(
                    "No more steps can run. Reply with `answer` only: what your tries showed.")))
        except Exception:  # noqa: BLE001 — the fallback below is still true
            logger.warning("smith4: the out-of-steps answer could not be had", exc_info=True)
        if not said:
            last = next((o for o in reversed(observations) if o.status == "finding" and o.said), None)
            if last is not None:
                said = f"The last thing I tried did not work: {' '.join(last.said.split())[:600]}"
        if not said:
            # WHAT THE TRIES SHOWED, IN THEIR OWN WORDS. Asked why images did
            # not show, Smith uploaded one, saved a dish with it and opened the
            # list — all of it worked — and the reply was "I have not changed
            # anything yet" (F&B live test, 2026-10-02).
            tried = [o.said.split("\n", 1)[0][:200] for o in observations
                     if tools.is_trial(o.tool) and o.status == "read" and o.said]
            if tried:
                said = "What I tried, and what it showed:\n" + "\n".join(f"- {t}" for t in tried[-6:])
        spent = f"time ({TURN_MINUTES:g} minutes)" if out_of_time else f"steps ({max_steps})"
        tail = (f"\n\nThis turn ran out of {spent} before I changed anything. "
                "Say “carry on” and I will pick up from there.")
        return Outcome(status="no_op", touched=list(touched), said=(said + tail) if said else (
            f"I have not changed anything yet — this turn ran out of {spent} "
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
    plan_mod.remember(ctx.out, planned, agreed=False, asked=ctx.ask)
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
