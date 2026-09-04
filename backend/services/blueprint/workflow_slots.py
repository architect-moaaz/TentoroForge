"""The pages that have nowhere to submit, as slots the workflow agent fills.

A create page is a form and a button. The button needs a workflow, and the
workflow has to exist before the composer can name it — `page_layouts` is told
which workflows a page launches and can only bind one that was authored.

Measured on a fresh 53-page build: eleven pages whose entire job is to create
something, and not one plain create workflow among the thirty-five authored.
The composer did the only two things left to it — invented a name, or left the
button dead — and sixteen of twenty-seven refused pages were one or the other:

    /documents/new       targets workflow 'createDocument', which this
                         application does not define
    /committees/new      Form 'Form' declares no action — it would do nothing

The thirty-five workflows are good ones. They are lifecycle verbs — "Raise a
Motion", "Register a Document and Upload a Version" — written from the
requirements, which is what the agent was asked for. Nothing asked whether the
pages that exist have anything to call.

SLOTS, NOT AN INSTRUCTION. `page_slots` learned this: three paragraphs telling
`page_contracts` that a filter belongs in `views` still produced six filtered
pages, because a free list admits a filtered page as a good answer. A sentence
saying "cover the create pages" competes with everything else in the prompt; a
list of the specific routes with nothing to submit to is a question with a
shape. The agent still decides what each workflow does and may still decline
one — a page can be a draft nobody submits — but it declines a named page
rather than never considering it.

NOT A VALIDATOR. Nothing here rejects a result. The workflow agent reads
`pages` already (§101) and this only puts the relevant ones where they cannot
be missed.
"""

from __future__ import annotations

from typing import Any

#: Patterns whose whole purpose is to submit something. `wizard` is a form in
#: several steps and ends in the same place.
_SUBMITTING_PATTERNS = frozenset({"form", "wizard", "create"})


def _submits(page: dict) -> bool:
    """Whether this page exists in order to write something.

    Route first, because it is what the page planner actually decides: the
    slot list names `/<entity>/new`, and that is true whatever pattern the
    contract later gives it. The pattern is the second signal, for a page that
    submits without living at `/new`.
    """
    route = str(page.get("route") or "")
    if route.endswith("/new") or route.endswith("/create"):
        return True
    return str(page.get("pattern") or "").strip().lower() in _SUBMITTING_PATTERNS


def _served(page_id: str, route: str, workflows: list) -> bool:
    """Whether some manual workflow already says it is launched from here."""
    for w in workflows:
        if not isinstance(w, dict):
            continue
        trigger = w.get("trigger")
        kind = trigger.get("kind") if isinstance(trigger, dict) else trigger
        if str(kind or "").strip().lower() != "manual":
            continue
        launched = {str(x) for x in (w.get("launchedFrom") or [])}
        if page_id in launched or route in launched:
            return True
    return False


def workflow_slots(doc: dict) -> list[dict]:
    """One slot per page that submits and has nothing to submit to."""
    workflows = list(doc.get("workflows") or [])
    out: list[dict] = []
    for page in doc.get("pages") or []:
        if page.get("status") == "DEPRECATED" or not _submits(page):
            continue
        pid, route = str(page.get("id") or ""), str(page.get("route") or "")
        if _served(pid, route, workflows):
            continue
        out.append({
            "page": pid,
            "route": route,
            "name": page.get("name") or route,
            "purpose": page.get("purpose") or "",
            # What it writes, so the workflow's steps have a real entity to
            # name rather than one inferred from the route's spelling.
            "entity": page.get("entity") or page.get("primaryEntity") or "",
        })
    return out


def workflow_slot_prompt(doc: dict) -> str:
    """The question these slots are the answer space for."""
    slots = workflow_slots(doc)
    if not slots:
        return ""
    return (
        f"{len(slots)} page(s) in this application exist in order to submit "
        "something, and none of them has a workflow to submit to. They are "
        "listed below.\n\n"
        "A create page whose workflow you do not author is a form with a dead "
        "button: the page composer is told which workflows each page launches "
        "and can only name one that exists, so it will either leave the "
        "control with no action or invent a name that resolves to nothing at "
        "run time. Both ship a screen that looks finished and does nothing.\n\n"
        "So for each page below, either author the workflow it needs and put "
        "that page's id in `launchedFrom`, or leave it alone deliberately — a "
        "page can legitimately be a draft that is saved and never submitted. "
        "Decline it because you decided to, not because it was not in front "
        "of you.\n\n"
        "This is in addition to the processes the requirements describe, not "
        "instead of them. A lifecycle workflow that happens to start at one of "
        "these pages covers it — name the page in `launchedFrom` and it is "
        "served."
    )
