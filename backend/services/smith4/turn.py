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
import os
import re
from pathlib import Path
from typing import Any, Callable

from services.smith import loop as loop_mod
from services.smith import plan as plan_mod
from services.smith import act, reads, tools, trials, web, writes
from services.smith.loop import Observation
from services.smith.understand_ask import UNREADABLE_HEAD
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
    "screen they used, as them (`open_page`, `try_workflow`, `try_request`) — so the change answers "
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
#: The writes that redo a page's code as a whole. The first of them in a turn
#: that gives no `because` is asked to size the change first: "change the
#: background to white" went to `write_page_code` — a full rewrite, seventeen
#: minutes — when one class in the file was the change (Mark 8, cxz95dd1,
#: 2026-10-16). The reason it gives is what the person is told.
SIZED = frozenset({"write_page_code", "rewrite_pages"})
SIZE_FIRST = (
    "Size the change before rewriting a page. From what you read of its code: a value, a class or a "
    "line changes — `edit_file` with `find` and `replace`; a section's content or one record's "
    "fields — the section verbs or `edit_definition`; the layout, a component that is replaced, or "
    "more than a few lines that move — call this again with `because`: one sentence saying which "
    "of those it is, in the person's terms. It is said to them as the reason.")
#: A step these answered never ran: asking for it again is not a repeat.
_NOT_RUN = frozenset({REPRODUCE_FIRST, PATCH_NEEDS_PROOF, NOT_ASKED_FOR, FAULT_NOT_SEEN, SIZE_FIRST})


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
#: What `done` hears, once, while the try after the change still fails.
FINISH_FIRST = ("Not done: the try after your change still fails — "
                "{what}. A change is done when the try that failed passes. Fix what the try "
                "points at and try it again; if it cannot be fixed this turn, say why with `answer`.")
#: KEEP AT IT. A turn's cap used to be its end: four of the six "say carry
#: on" endings in two weeks of forge-v3 chats were budgets, not dead ends
#: (2026-10-17). A turn whose steps are up is granted more, in slices, for
#: as long as it is getting somewhere — a new read, a new try, a change
#: since the last slice — up to a hard time and step limit. A turn going
#: round in circles makes only refused steps, which is not progress, and
#: ends. A turn the platform runs unattended keeps the budget it was given.
FINISH_STEPS = 8
KEEP_AT_IT_TIME_S = float(os.environ.get("FORGE_SMITH_KEEP_AT_IT_S") or 45 * 60)
HARD_MAX_STEPS = int(os.environ.get("FORGE_SMITH_HARD_MAX_STEPS") or 120)
KEEP_AT_IT = ("Your steps were up, but you are getting somewhere, so you have {n} more. Keep at it "
              "until the try that failed passes. Do not end on a failing try unless something outside "
              "this application stops you — then say with `answer` exactly what you tried, what still "
              "fails, and what you need.")
#: What the loop is told when its reply could not be read: once, then the
#: turn ends on what it has rather than on a question that throws it away.
UNREADABLE_RETRY = ("Your last reply could not be read as a step. Reply with the JSON object only — "
                    "{\"tool\": …, \"args\": …, \"why\": …} — and nothing around it.")
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
    # A TEMPLATE WAITING TO BE USED IS ALREADY READ. Its facts are on the page
    # (`context.template_page`), and the first move is usually to ask "the
    # exact same app, or something like it?" — which LOOK_FIRST would refuse
    # as unread, spending a step to look at nothing new.
    from services import project_templates as _templates
    _staged = _templates.pending(ctx.out)
    if _staged:
        observations.append(Observation(tool="template", status="read", said=(
            f"This project was started from the template “{_staged.get('name')}”; "
            "what it holds is on the page.")))
    bench = trials.Bench(ctx.out)
    # THE PERSON'S WORDS GO WITH EVERY BRIEF THIS TURN HANDS ON (`asked`).
    from services.smith.asked import ASKED
    asked = asked_text(ctx)
    token = ASKED.set(asked)
    from services.smith import file_edit
    started = {p.get("id") for p in file_edit.load_patches(ctx.out)}
    try:
        # A CALLER'S OWN BUDGET IS A BUDGET; the chat's default is a floor the
        # turn keeps at it past while it is getting somewhere.
        out = _run(ctx, choose, list(history or []), observations,
                   max_steps or loop_mod.MAX_STEPS, bench, keep_at_it=max_steps is None)
    finally:
        ASKED.reset(token)
        bench.close()
    # THE TURN LEAVES A LINE IN THE NOTEBOOK: what it read, tried, changed and
    # left — so the next turn starts where this one stopped instead of at the
    # slice and the catalogue (2026-10-17).
    from services.smith import notebook
    notebook.record(ctx.out, asked, observations, out)
    out.steps = [o.tool for o in observations]
    # A PLATFORM PATCH IS KEPT ONLY ON PROOF: a try after the last edit that
    # passed, and nothing that failed before still failing.
    patches = file_edit.load_patches(ctx.out)
    pending = [p["id"] for p in patches if p.get("id") not in started and p.get("status") == "pending"]
    older = [p["id"] for p in patches if p.get("id") in started and p.get("status") == "pending"]
    if pending or older:
        verdict = patch_verdict(observations)
        said: list[str] = []
        if pending and verdict == "inconclusive":
            # A TRY THAT COULD NOT RUN DECIDES NOTHING. Personal Finance's engine
            # patch fixed the date fault; the try after it met the server
            # restarting, read as "failed the same way", and the patch was taken
            # back — the next turn papered over four pages instead (pcn4owv7,
            # 2026-10-15). It stays pending until a try that ran decides it.
            said.append("The try after the change could not run to the end (the app's server was not "
                        "there to answer), so it decides nothing: the change stays, untried, until a "
                        "try that runs says whether it works.")
            # AND THE CHANGE IS SAID AS MADE. A turn whose only change was this
            # patch opened with "Nothing needed doing." and self-heal reported
            # "no fix produced" above "the change stays" (pah7lhfz, 2026-10-21).
            out.untried = True
            made = [p for p in patches if p.get("id") in pending]
            for p in made:
                path = f"app/{p.get('path')}"
                if p.get("path") and path not in out.touched:
                    out.touched.append(path)
            lead = "Nothing needed doing."
            if out.said.strip().startswith(lead):
                out.said = " ".join(
                    f"Changed the platform's `{p.get('path')}` for this app"
                    + (f": {str(p.get('why')).rstrip('.')}" if p.get("why") else "") + "."
                    for p in made) + out.said.strip()[len(lead):]
        elif pending:
            said += file_edit.settle(ctx.out, pending, verdict == "proven")
        if older and verdict == "proven":
            said += file_edit.settle(ctx.out, older, True)
        if said:
            out.said = (out.said + "\n\n" if out.said else "") + " ".join(said)
    return out


def inconclusive(said: str) -> bool:
    """A try that never reached the app: the server restarting or gone, or
    the copy that could not start. It says nothing about the change."""
    text = said or ""
    return (trials.SERVER_RESTARTED in text or bool(trials._SERVER_GONE.search(text))
            or text.startswith("The app could not be started"))


def patch_verdict(observations: list[Observation]) -> str:
    """What the tries after the last edit say about it: `proven` (the last
    one ran and passed, nothing that failed before still fails), `failed`,
    `inconclusive` (the last one could not run), or `untried`."""
    edits = [i for i, o in enumerate(observations) if o.tool == "edit_file" and _is_change(o)]
    after = [o for o in observations[(edits[-1] + 1 if edits else 0):] if tools.is_trial(o.tool)]
    if not after:
        return "untried"
    last = after[-1].said or ""
    if inconclusive(last):
        return "inconclusive"
    if trials.failed(last) or _still_failing(observations):
        return "failed"
    return "proven"


def _trial_key(o: Observation) -> str:
    a = o.args or {}
    return "|".join([o.tool, str(a.get("workflow") or a.get("path") or a.get("route") or ""),
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


def _app_exists(ctx: Any) -> bool:
    """There is an application to try. Before the first build there is only
    a definition: `open_page` then has no app to start, and the try-first
    rules sent every define turn into one (FileNotFoundError on `app/`,
    60v142ju and 6ysfw182, 2026-10-12) before it could say what it wrote."""
    try:
        return (Path(ctx.out) / "app" / "package.json").is_file()
    except Exception:  # noqa: BLE001 — no output dir: nothing to try
        return False


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
    # NOT DONE WHILE THE TRY STILL FAILS. "Say carry on and I will keep at it"
    # ended turns that had the fault in hand and steps left (97l5iqsp,
    # cxz95dd1, 2026-10). Once: a turn that cannot fix it says why instead.
    # (A try failing the way it did before the change is `_unproven`'s nudge
    # above; this is the failure that is new after the change.)
    failing = last_try_failed(observations)
    if landed and failing and not _still_failing(observations) and FINISH_FIRST.split(":", 1)[0] not in said:
        return FINISH_FIRST.format(what=failing)
    return ""


def kept_at_it(observations: list[Observation], elapsed_s: float | None = None) -> str:
    """"I kept at this for 31 minutes (57 steps)" — what an ending on a
    failing try owes the person: that the time was spent, not that it was
    not. Empty when the turn was short."""
    steps = len([o for o in observations if o.said not in _NOT_RUN and o.status != "error"])
    minutes = int((elapsed_s or 0) // 60)
    if minutes < 5 and steps < 20:
        return ""
    when = f"{minutes} minutes" if minutes >= 1 else "a while"
    return f"I kept at this for {when} ({steps} steps). "


def _failing_note(observations: list[Observation], elapsed_s: float | None = None) -> str:
    """Said after what landed when a turn ends with a try still failing: a
    change is reported, and so is that it did not fix what it was for."""
    kept = kept_at_it(observations, elapsed_s)
    still = _still_failing(observations)
    if still:
        return ("\n\n" + kept + "It still does not work: I tried it again after the change and it failed "
                "the same way. Say “carry on” and I will continue from here.")
    fresh = _new_failures(observations)
    if fresh:
        return ("\n\n" + kept + "After the change, this was tried and does not work: " + "; ".join(fresh[:4])
                + ". Say “carry on” and I will continue from here.")
    return ""


def standing_faults(doc: dict | None, output_dir: str = "") -> list[str]:
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
    # A CALL TO AN OUTSIDE SERVICE THAT ITS DOCUMENTATION, OR THE SERVICE
    # ITSELF, SAYS IS WRONG — the live call made once its key is stored.
    try:
        from services.blueprint import api_reference
        out += api_reference.standing(output_dir, doc)
    except Exception:  # noqa: BLE001
        logger.debug("[smith] service check failed", exc_info=True)
    return out


def _run(ctx: Ctx, choose: Choose, history: list, observations: list[Observation],
         max_steps: int, bench: "trials.Bench | None" = None, *, keep_at_it: bool = False) -> Outcome:
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
    if not observations and not ctx.unattended:
        # A CALL SHOWN LAST TURN, ANSWERED NOW. The yes sends exactly what was
        # shown — not whatever the model would write again — and anything
        # else drops it, said, so the model knows it did not go.
        replied = act.answer_held(ctx.out, ctx.message, said=web.person_said(ctx.ask, history))
        if replied:
            observations.append(Observation(tool=replied[0], args=replied[1], status="read", said=replied[2]))
    faults = standing_faults(ctx.doc(), ctx.out) if not observations else []
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
    if not observations:
        # WHAT THE BUILD SETTLED FOR TO FINISH (`AuthorRefusal.settle`): each
        # the safe choice where a check refused the author's work twice — a
        # screen the administrator alone may open, charts short of the house
        # standard. Not faults: the person's decisions, waiting to be made.
        try:
            from services.blueprint.orchestrator import settled_for
            settled = settled_for(ctx.out)
        except Exception:  # noqa: BLE001
            settled = []
        if settled:
            observations.append(Observation(tool="settled_in_build", status="read", said=(
                "To finish the build, Forge settled for these where a check kept refusing the work — each "
                "the safe choice, none of them a fault:\n- " + "\n- ".join(settled[:10])
                + "\nWhen what they ask touches one, say what was settled and change it as they ask; "
                  "otherwise leave them unmentioned. One the application already does differently is done.")))
    landed: list[str] = []
    touched: list[str] = []
    last: Outcome | None = None

    import time as _time
    turn_started = _time.monotonic()
    from services.smith import narrate
    try:
        from services.smith import notebook as _nb0
        _known = bool(_nb0.entries(ctx.out))
    except Exception:  # noqa: BLE001
        _known = False
    tell(ctx, narrate.opening(_known, _app_exists(ctx), defined=bool(ctx.doc())))
    told_up_to = 0
    unreadable = 0
    budget, since, _step = max_steps, 0, 0
    while True:
        if _step >= budget:
            more = more_steps(observations, since=since, steps=_step,
                              elapsed_s=_time.monotonic() - turn_started,
                              unattended=ctx.unattended or not keep_at_it)
            if not more:
                break
            budget, since = budget + more, len(observations)
            logger.info("[smith-step] keeping at it: %d more steps at step %d, %.0fs in",
                        more, _step, _time.monotonic() - turn_started)
            observations.append(Observation(tool="done", status="error", said=KEEP_AT_IT.format(n=more)))
            tell(ctx, "My steps were up, but this is getting somewhere, so I am carrying on…")
        _step += 1
        from services.smith4.definition import brief_of
        # WHAT THE LAST STEP SHOWED, IN PLAIN WORDS, BEFORE THE NEXT IS CHOSEN.
        for _o in observations[told_up_to:]:
            if _o.said in _NOT_RUN or _o.status == "error":
                continue
            tell(ctx, narrate.seen(_o.tool, _o.args, _o.status, _o.said or "",
                                   after_change=any(_is_change(x) for x in observations[:observations.index(_o)])))
        told_up_to = len(observations)
        if _step > 1:
            # WHAT THIS TURN KNOWS SO FAR, KEPT IN CASE IT IS LOST. A turn the
            # process loses never reaches the notebook's end-of-turn line.
            from services.smith import notebook as _nb
            _nb.checkpoint(ctx.out, ctx.ask or ctx.message or "", observations)
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
        tell(ctx, narrate.starting(tool, args))
        # SAID TO THE LEDGER, so a long turn can be reported on while it runs.
        try:
            from services import run_registry as _rr
            _rr.turn_step(ctx.out, step_line(_step, tool, args))
        except Exception:  # noqa: BLE001 — a note, never the turn
            pass

        if tool == "ask_user" and str(args.get("question") or "").startswith(UNREADABLE_HEAD):
            # A REPLY NOBODY COULD READ IS NOT THE END OF THE TURN'S WORK. Four
            # of TCommerce's turns had read the code and tried the cart, then
            # ended on "I could not turn that into a change I am sure of" and
            # the person retyped the report three times (ihf6pjga, 2026-10-06).
            # Asked once more for a readable step; failing that, the turn ends
            # on what it did and found, and the next one carries on from it.
            unreadable += 1
            if unreadable == 1:
                observations.append(Observation(tool=tool, args=args, status="error", said=UNREADABLE_RETRY))
                continue
            if landed:
                return _finished(landed, touched, last, note=(
                    "\n\nI stopped there: my next step could not be worked out. Say “carry on” "
                    "and I will pick up from what is above."))
            seen = what_was_seen(observations)
            if seen:
                return Outcome(status="no_op", touched=list(touched), said=(
                    seen + "\n\nI stopped there: my next step could not be worked out. Say “carry "
                           "on” and I will pick up from what is above."))
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
        if tool == "answer" and not landed and _app_exists(ctx) \
                and not any(tools.is_act(o.tool) and o.status == "read" for o in observations):
            # An answer after a call to a service reports that call; it is not
            # about what the application does, so nothing there needs trying.
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
        if tool == "done" and _app_exists(ctx):
            first = _before_done(observations, landed)
            if first:
                observations.append(Observation(tool=tool, args=args, status="error", said=first))
                continue
        if tool in tools.TERMINAL_NAMES or not tool:
            ended = _ended(tool, args, landed, touched, last, observations)
            if tool != "answer" and ended.status not in ("asked",):
                ended.said += _failing_note(observations, _time.monotonic() - turn_started)
            if tool == "done" and landed and ended.status == "resolved":
                # A FIX ENDS WITH ITS ACCOUNT — what was happening, what changed,
                # what proved it — and leaves a guard the checks run again.
                from services.smith import account, guards
                try:
                    ended.said = account.compose(ctx.ask or ctx.message or "", observations, ended.said)
                except Exception:  # noqa: BLE001 — the receipt stands without the account
                    logger.debug("[smith] the fix's account could not be composed", exc_info=True)
                guards.record(ctx.out, ctx.ask or ctx.message or "", observations)
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

        if tools.is_act(tool):
            step_ = act.run(tool, args, said=web.person_said(ctx.ask, history), output_dir=ctx.out,
                            unattended=ctx.unattended, doc=ctx.doc())
            logger.info("[smith-act] %s %s -> %s", tool, {k: str(v)[:80] for k, v in args.items()},
                        " | ".join(step_.said.splitlines()[:2])[:300])
            if step_.ask:
                return _finished(landed, touched, Outcome(status="asked", said=step_.ask,
                                                          options=list(step_.options)))
            observations.append(Observation(tool=tool, args=args, status="read", said=step_.said))
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
            elif not tried:
                claimed = str(args.get("requested") or "").strip().lower() in ("true", "1", "yes")
                if not claimed:
                    observations.append(Observation(tool=tool, args=args, status="error", said=REPRODUCE_FIRST))
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
            # SEEN FIRST, SIZED SECOND. Once the fault has been seen (or the change
            # is the one they asked for), a whole-page rewrite still says why an
            # edit will not do — once a turn — before it runs.
            held = size_first(tool, args, observations)
            if held is not None:
                observations.append(held)
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
            said = what_was_seen(observations)
        spent = kept_at_it(observations, _time.monotonic() - turn_started) or f"This turn ran out of steps ({budget}). "
        tail = (f"\n\n{spent}I changed nothing: I was still working out where the fault is. "
                "Say “carry on” and I will continue from here — what I read and tried is kept.")
        return Outcome(status="no_op", touched=list(touched), said=(said + tail) if said else (
            f"{spent}I have not changed anything yet — I was still looking into it. "
            "Say “carry on” and I will continue from here; what I read and tried is kept."))
    failing = _failing_note(observations, _time.monotonic() - turn_started)
    if not failing and _unproven(observations).startswith(UNPROVEN):
        # The change landed on the last step the cap allowed, untried.
        failing = ("\n\nI have not yet tried it again since the change, so I cannot say it works "
                   "yet — this turn ran out of steps. Say “carry on” and I will try it.")
    note = failing or loop_mod.remaining_note(observations, capped=True).replace(
        f"{loop_mod.MAX_STEPS} steps", f"{budget} steps")
    return _finished(landed, touched, last, note=note)


def tell(ctx: Ctx, text: str) -> None:
    """One plain-words line to the panel's thinking trail while the turn
    runs (`thought`, kind `step`). Never raises; a turn without a listener
    (tests, the platform's own turns) says nothing."""
    if not text or ctx.unattended or not callable(getattr(ctx, "reasoning", None)):
        return
    try:
        ctx.reasoning(text, kind="step")
    except TypeError:
        try:
            ctx.reasoning(text)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001 — a line to the panel never costs the turn
        logger.debug("[smith] could not narrate a step", exc_info=True)


def asked_text(ctx: Ctx) -> str:
    """The person's words, as every brief this turn hands on gets them. A
    plan step says which part it does; a repair the platform runs after a
    change says what the person asked for and that this is the repair of
    what doing it broke — so the repair stays inside their ask instead of
    becoming a change nobody asked for (F2, qpqhdugb 2026-10-16)."""
    asked = ctx.ask or ctx.message or ""
    if ctx.asked_from and ctx.asked_from not in asked:
        if ctx.unattended:
            return (f"{ctx.asked_from}\n(The person asked for that. This turn repairs what making that "
                    f"change broke, and nothing else: {asked})")
        return f"{ctx.asked_from}\n(This turn does one part of it: {asked})"
    return asked


def last_try_failed(observations: list[Observation]) -> str:
    """The first line of the last try after the last change when it failed
    (a failure that ran — a try that could not run decides nothing); ""
    otherwise."""
    changes = [i for i, o in enumerate(observations) if _is_change(o)]
    if not changes:
        return ""
    after = [o for o in observations[changes[-1] + 1:] if tools.is_trial(o.tool) and o.status == "read"]
    if not after:
        return ""
    said = after[-1].said or ""
    if inconclusive(said) or not trials.failed(said):
        return ""
    return " ".join(said.split("\n", 1)[0].split())[:200]


def progressed(observations: list[Observation], since: int) -> bool:
    """Whether the steps since `since` got anywhere: a read or a try that ran
    (status `read`), a change that landed (`resolved` with files) or a
    finding — anything but refused steps and errors."""
    for o in observations[since:]:
        if o.status == "read" or o.status == "finding" or (o.status == "resolved" and _is_change(o)):
            return True
    return False


def more_steps(observations: list[Observation], *, since: int, steps: int, elapsed_s: float,
               unattended: bool = False) -> int:
    """How many steps a turn whose budget is up may still have: a slice of
    `FINISH_STEPS` while it is making progress and under the hard limits;
    0 when it is going round in circles, too old, or run by the platform."""
    if unattended:
        return 0
    if elapsed_s > KEEP_AT_IT_TIME_S or steps >= HARD_MAX_STEPS:
        return 0
    if not progressed(observations, since):
        return 0
    return min(FINISH_STEPS, HARD_MAX_STEPS - steps)


def what_was_seen(observations: list[Observation]) -> str:
    """What a turn that changed nothing can still say: the last finding, or
    what its tries showed in their own words. Asked why images did not show,
    Smith uploaded one, saved a dish with it and opened the list — all of it
    worked — and the reply was "I have not changed anything yet" (F&B live
    test, 2026-10-02)."""
    last = next((o for o in reversed(observations) if o.status == "finding" and o.said), None)
    if last is not None:
        return f"The last thing I tried did not work: {' '.join(last.said.split())[:600]}"
    tried = [o.said.split("\n", 1)[0][:200] for o in observations
             if tools.is_trial(o.tool) and o.status == "read" and o.said]
    if tried:
        return "What I tried, and what it showed:\n" + "\n".join(f"- {t}" for t in tried[-6:])
    return ""


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


#: Said with what a no-change turn tried: where the person is matters.
#: "During signup it says Display Name is required" was answered "Nothing
#: needed doing" after a signup that worked on the preview — the tester was
#: on the address of an earlier publish, which keeps the earlier build
#: (pcn4owv7, 2026-10-15 11:40).
STILL_FAILS_FOR_YOU = ("If it still fails for you, tell me the address you are on and what the page says "
                       "— an address from an earlier publish keeps the earlier build; the preview and the "
                       "latest publish have the current one.")


def _ended(tool: str, args: dict, landed: list[str], touched: list[str],
           last: Outcome | None, observations: list[Observation] | None = None) -> Outcome:
    if tool == "ask_user":
        question = str(args.get("question") or "").strip()
        options = [str(o).strip() for o in (args.get("options") or []) if str(o).strip()]
        if question:
            return Outcome(status="asked", said=question, options=options, touched=list(touched))
    if tool == "answer" and not landed:
        said = str(args.get("text") or "").strip()
        if said:
            return _finished([said], touched, Outcome(status="no_op", said=said))
    if tool == "done" and not landed and not (last and last.said):
        # NOT "NOTHING NEEDED DOING" AFTER A TRY. What was tried and what it
        # showed is the answer; the default is a shrug.
        tried = [o.said.split("\n", 1)[0][:200] for o in (observations or [])
                 if tools.is_trial(o.tool) and o.status == "read" and o.said]
        if tried:
            said = ("I changed nothing this turn. What I tried, and what it showed:\n"
                    + "\n".join(f"- {t}" for t in tried[-6:]) + "\n\n" + STILL_FAILS_FOR_YOU)
            return _finished([said], touched, Outcome(status="no_op", said=said))
    return _finished(landed, touched, last)


def size_first(tool: str, args: dict, observations: list) -> Observation | None:
    """The observation a whole-page rewrite without a `because` gets, once a
    turn; None when the call may run. A reason given, or the rule already
    heard this turn, lets it through — the rule is a question asked once,
    not a gate."""
    if tool not in SIZED or str(args.get("because") or "").strip():
        return None
    if any(o.said == SIZE_FIRST for o in observations):
        return None
    return Observation(tool=tool, args=args, status="error", said=SIZE_FIRST)


def step_line(n: int, tool: str, args: dict) -> str:
    """One short line for a step: the tool, what it is about, and — for a
    change — why that change: the `because` of a rewrite, the `why` of an
    edit. "step 6: write_page_code /" told the person nothing they could
    object to; the reason is what lets them say "no, just the background"
    at minute one rather than minute seventeen (Mark 8, 2026-10-16)."""
    about = ""
    for key in ("route", "path", "name", "workflow", "entity", "page"):
        if args.get(key):
            about = str(args[key])[:60]
            break
    who = f" as {args['as']}" if args.get("as") else ""
    reason = str(args.get("because") or (args.get("why") if tool in ("edit_file", "edit_definition") else "") or "").strip()
    reason = " ".join(reason.split())[:140]
    return f"step {n}: {tool or '-'}" + (f" {about}" if about else "") + who + (f" — {reason}" if reason else "")


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


__all__ = ["turn", "Choose", "LOOK_FIRST", "NOTHING_TRIED", "UNPROVEN", "STILL_FAILING", "SIZE_FIRST", "SIZED"]
