"""“it crashed” and “it's really slow”, answered with what actually happened.

These two sentences are on the owner's phrasebook under *vague, cross, or
both*, and they were the only entries on it whose answer was not a missing
verb. Every other gap was something Smith could be taught to do. These two
were something the running application had to say first: an owner was the
only telemetry Forge had, so the sentence they typed was also the entire
contents of the report.

Now the application reports its own crashes and its own slow responses into
``<output_dir>/.forge/incidents.jsonl`` (:mod:`services.incident_ledger`), and
this module is the reading of that file that a person gets back.

THE SHAPE OF THE ANSWER IS THE BUILD'S. `blueprint.assembly.verify_dispatches`
dry-runs every control through the app's own engine before the app ships and
fails naming the route, the control, the workflow and the step. That is the
same information, at build time, that a crash carries at run time, so an
owner who saw::

    /cases: Table.rowActions[0] 'Approve' runs approve-case — step 'notify'
    (send_email): recipient is empty

when it was built reads the same sentence when it breaks in front of somebody.

WHAT IS OFFERED, AND WHAT IS NOT
================================
Where a crash names a control or a workflow, the repair is real and it is
offered as a sentence a click can say — the same convention as
:mod:`services.smith.limits`, whose options classify back to their own verbs.

Slowness is answered with the measurement and refused as a repair, because
there is no verb here that makes an application faster. What is measured is
stated in the answer rather than implied: the duration of a handler inside the
app's own server process, which is not the browser's render, not the network
between a customer and the server, and not a cold start before that code ran.
An owner told "your app is fine" on the strength of a number that never
covered the thing they were complaining about is worse off than one told
nothing.
"""

from __future__ import annotations

from typing import Any

from services import incident_ledger
from services.smith.labels import normalise

#: How many distinct crashes are described in full before the rest are
#: counted. A person asking what broke wants the thing that broke, not a log.
SHOWN = 3


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if isinstance(i, dict) and i.get("status") != "DEPRECATED"]


def _workflow_name(doc: dict, key: str) -> str:
    """The workflow's own name, from whichever of its names the app reported.

    A control's `workflow` prop carries the Blueprint id and the projected
    definition is filed under a slug of the name, so the ledger holds one or
    the other. Both are matched — `normalise` reads "approve-case" and
    "Approve Case" as the same words, which is exactly the difference between
    a slug and its name. An unknown key is returned as it came, which at least
    names something somebody can search for.
    """
    if not key:
        return ""
    want = normalise(key)
    for wf in _live(doc.get("workflows")):
        name = str(wf.get("name") or "")
        if want in {normalise(str(wf.get("id") or "")), normalise(name)}:
            return name or key
    return key


def _page_name(doc: dict, route: str) -> str:
    if not route:
        return ""
    want = normalise(route)
    for page in _live(doc.get("pages")):
        if normalise(str(page.get("route") or "")) == want:
            return str(page.get("name") or route)
    return route


def _where(doc: dict, inc: dict) -> str:
    """Where this happened, in the owner's words: the screen, or the process."""
    page = _page_name(doc, str(inc.get("route") or ""))
    if page:
        return f"on **{page}**"
    workflow = _workflow_name(doc, str(inc.get("workflow") or ""))
    if workflow:
        return f"in **{workflow}**"
    return ""


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def change_before(doc: dict, when: str) -> dict:
    """The last recorded change made before `when`, or {}.

    A FACT ABOUT ORDER, NOT ABOUT CAUSE. The answer says a crash first appeared
    after a particular change; it does not say the change caused it, because
    nothing here knows that. What it buys is the offer of an undo, which is
    the one move that settles the question without anybody having to be right
    about it first.
    """
    if not when:
        return {}
    latest: dict = {}
    for entry in (doc.get("changeHistory") or []):
        if not isinstance(entry, dict):
            continue
        at = str(entry.get("at") or "")
        if at and at <= when:
            latest = entry
    return latest


# --------------------------------------------------------------------------- #
# "it crashed"
# --------------------------------------------------------------------------- #

def describe_crash(doc: dict, crash: dict) -> list[str]:
    """One crash, in the same shape the build-time dry run names a bad wire."""
    control = str(crash.get("control") or "")
    label = str(crash.get("label") or "")
    named = f"**{label}**" if label else (f"`{control}`" if control else "Something")
    where = _where(doc, crash)
    head = f"{named} {where}".strip() if where else named
    lines = [f"- {head} failed {_times(int(crash.get('count') or 1))}"
             + (f", most recently {crash.get('lastSeen')}" if crash.get("lastSeen") else "")
             + "."]

    workflow = _workflow_name(doc, str(crash.get("workflow") or ""))
    step = str(crash.get("step") or "")
    if workflow and step:
        action = str(crash.get("actionType") or "")
        lines.append(f"  It runs **{workflow}**, and it stopped at the step "
                     f"`{step}`" + (f" ({action})" if action else "") + ".")
    elif workflow:
        lines.append(f"  It runs **{workflow}**.")

    message = " ".join(str(crash.get("message") or "").split())
    if message:
        lines.append(f"  What it said: `{message[:240]}`")
    frames = incident_ledger.stack_frames(crash, limit=2)
    if frames:
        lines.append("  " + " · ".join(f"`{f}`" for f in frames))
    keys = [str(k) for k in (crash.get("payloadKeys") or [])]
    if keys:
        # The names of what the control sent, which is all that ever leaves the
        # application — the values are the owner's and stay there.
        lines.append("  It was sent: " + ", ".join(f"`{k}`" for k in keys) + ".")
    return lines


def repair_options(doc: dict, crashes: list[dict]) -> list[str]:
    """The repairs the crashes themselves name, as sentences a click can say.

    Only what a crash actually named. A crash with no workflow and no route
    offers nothing, because the alternative is offering a change to something
    that was picked because it was nearby.
    """
    options: list[str] = []
    for crash in crashes:
        workflow = _workflow_name(doc, str(crash.get("workflow") or ""))
        step = str(crash.get("step") or "")
        if workflow:
            said = (f"Change the {workflow} process so the {step} step stops failing"
                    if step else f"Change the {workflow} process so it stops failing")
            if said not in options:
                options.append(said)
            continue
        route = str(crash.get("route") or "")
        if route and str(crash.get("where") or "") == "page_render":
            said = f"Lay {route} out again"
            if said not in options:
                options.append(said)
    return options[:3]


def crash_answer(output_dir: str, doc: dict) -> tuple[str, list[str]]:
    """What has been crashing, and the repairs those crashes name."""
    found = incident_ledger.crashes(output_dir)
    if not found:
        return (
            "Nothing has been reported as crashing. The application reports "
            "its own failures — an error on a screen, a process that stops "
            "part-way, a button whose action throws — and none have come in.\n\n"
            "If you are looking at one right now, it may not have reached me "
            "yet: reports only come from a *built and running* application, "
            "and never from a preview that has not been started.\n\n"
            "If something behaves wrongly rather than failing — a page that "
            "opens the wrong screen, a list that stays empty — tell me what "
            "you expected to happen and I will check it against how the app "
            "is set up, or I can sign in and read every page as it renders.",
            ["Verify & fix"])

    shown, rest = found[:SHOWN], found[SHOWN:]
    lines = ["Here is what has been failing."]
    for crash in shown:
        lines += [""] + describe_crash(doc, crash)
    if rest:
        total = sum(int(c.get("count") or 1) for c in rest)
        lines += ["", f"And {len(rest)} other "
                      f"{'thing' if len(rest) == 1 else 'things'}, "
                      f"{_times(total)} between them."]

    newest = shown[0]
    preceding = change_before(doc, str(newest.get("firstSeen") or ""))
    options = repair_options(doc, shown)
    if preceding.get("userRequest"):
        from services.smith.revert import undoable, what_would_be_undone
        asked = " ".join(str(preceding["userRequest"]).split())
        first = str(newest.get("label") or newest.get("control") or "The first of those")
        lines += ["", f"**{first}** first failed after you asked for “{asked}”. "
                      "That is the order it happened in, not a claim that one "
                      "caused the other — but it is the thing to try first, "
                      "because undoing it settles the question."]
        # Only offer the undo that would actually reverse THAT change: an
        # `undo` reverses the most recent one, and offering it for an older
        # change would put back something nobody asked about.
        latest = undoable(doc) or {}
        if latest.get("version") == preceding.get("version"):
            options.append(f"Undo “{what_would_be_undone(doc)}”")
    return "\n".join(lines), options[:4]


# --------------------------------------------------------------------------- #
# "it's really slow"
# --------------------------------------------------------------------------- #

#: Said whenever a number is said, because a number without it invites the
#: reader to think it covers what they were complaining about.
MEASURED = (
    "What I measure is how long the application's own server takes to do the "
    "work — not how long the page takes to paint in front of you, not the "
    "connection between a person and the server, and not the first request "
    "after it has been idle, which is always the slow one."
)


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.1f}s"


def slow_answer(output_dir: str, doc: dict) -> tuple[str, list[str]]:
    """What has been slow, measured — and what I cannot do about it."""
    found = incident_ledger.slow(output_dir)
    if not found:
        return (
            "Nothing has come in as slow. The application times every data "
            "read and write and every process it runs, and reports the ones "
            "that take longer than it is told to expect — and none have.\n\n"
            + MEASURED + "\n\nSo if it is slow in front of you, it is slow "
            "somewhere I am not looking. Tell me which screen and what you "
            "were doing, and I will tell you what the server was doing at the "
            "time.",
            [])

    threshold = next((int(s["thresholdMs"]) for s in found if s.get("thresholdMs")), 0)
    lines = ["Here is what has been taking too long"
             + (f" — anything over {_seconds(threshold)}." if threshold else ".")]
    options: list[str] = []
    for slow in found[:SHOWN]:
        workflow = _workflow_name(doc, str(slow.get("workflow") or ""))
        label = str(slow.get("label") or "")
        entity = str(slow.get("entity") or "")
        operation = str(slow.get("operation") or "")
        if workflow:
            what = f"**{workflow}**" + (f", run from {label}" if label else "")
        elif entity:
            what = f"`{operation}` on **{entity}**"
        else:
            what = f"`{operation}`"
        lines.append(f"- {what} — {_times(int(slow['count']))}, "
                     f"{_seconds(int(slow['averageMs']))} on average and "
                     f"{_seconds(int(slow['worstMs']))} at worst.")
        if workflow:
            said = f"Simplify the {workflow} process so it does less"
            if said not in options:
                options.append(said)

    lines += ["", MEASURED, "",
              "**I cannot make it faster on its own.** There is no change I "
              "can make whose only effect is speed — what I can do is change "
              "what the application *does*, and a process that does less "
              "finishes sooner."]
    if not options:
        lines += ["", "Nothing above is a process I can shorten: these are the "
                      "plain reads and writes the screens make, and they are "
                      "already the smallest version of themselves."]
    return "\n".join(lines), options[:3]


# --------------------------------------------------------------------------- #
# The shape a tool handler needs
# --------------------------------------------------------------------------- #

def run(output_dir: str, *, kind: str = incident_ledger.KIND_CRASH) -> dict:
    """Answer one of the two sentences from a project directory."""
    from services.smith.engine_blueprint_adapter import load_engine_doc

    doc = load_engine_doc(str(output_dir)) or {}
    answer, options = (slow_answer(str(output_dir), doc)
                       if kind == incident_ledger.KIND_SLOW
                       else crash_answer(str(output_dir), doc))
    return {"applied": False, "edited_paths": [], "answer": answer,
            "options": options, "kind": kind}


__all__ = ["SHOWN", "MEASURED", "change_before", "describe_crash",
           "repair_options", "crash_answer", "slow_answer", "run"]
