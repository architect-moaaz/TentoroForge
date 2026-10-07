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
    # A LIST THAT ADDS ITS RECORDS is the create page now (`addsHere`): the
    # form is a panel on it, and it has as much need of a workflow to call.
    if page.get("addsHere"):
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


def _norm(text: Any) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in str(text or "")).split())


def _named(action: str, page_id: str, route: str, workflows: list) -> bool:
    """Whether a manual workflow launched from this page is the one this
    action names — "Accept order" and a workflow called "Accept Order"."""
    want = _norm(action)
    for w in workflows:
        if not isinstance(w, dict):
            continue
        launched = {str(x) for x in (w.get("launchedFrom") or [])}
        if (page_id in launched or route in launched) and _norm(w.get("name")) == want:
            return True
    return False


def section_slots(doc: dict) -> list[dict]:
    """The things a screen's sections say a person does there and that no
    workflow launched from the screen does yet: adding (`addsHere`) and each
    named action ("Accept order", "Approve refund").

    A SCREEN IS ITS ACTIONS. Every workflow Mozato had (forge-v3, 2026-10-06)
    created or submitted something, one per create page, because create pages
    were the only screens this agent was asked about: nothing accepted an
    order, marked it ready or delivered it. A section names its actions, so the
    question carries them."""
    from services.blueprint.screen_parts import section_audience

    workflows = list(doc.get("workflows") or [])
    ents = {str(e.get("id")): e.get("name") for e in (doc.get("data") or {}).get("entities") or []
            if isinstance(e, dict)}
    out: list[dict] = []
    for page in doc.get("pages") or []:
        if not isinstance(page, dict) or page.get("status") == "DEPRECATED":
            continue
        pid, route = str(page.get("id") or ""), str(page.get("route") or "")
        for sec in page.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            entity = str(sec.get("entity") or "")
            wanted = list(sec.get("actions") or [])
            if sec.get("addsHere") and entity:
                wanted.insert(0, f"Add {ents.get(entity) or entity}")
            for action in dict.fromkeys(a for a in wanted if str(a).strip()):
                if _named(action, pid, route, workflows):
                    continue
                out.append({"page": pid, "route": route, "section": sec.get("key"),
                            "entity": entity, "action": action,
                            # Who does it, when the section is only some roles'
                            # — the lead approves the refund, not the agent.
                            **({"by": section_audience(doc, sec)} if section_audience(doc, sec) else {})})
    return out


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
            "entity": page.get("entity") or page.get("primaryEntity")
                      or (page.get("data") or {}).get("primaryEntity") or "",
            **({"addsHere": True} if page.get("addsHere") else {}),
        })
    return out


def workflow_slot_prompt(doc: dict) -> str:
    """The question these slots are the answer space for."""
    slots = workflow_slots(doc)
    actions = section_slots(doc)
    if not slots and not actions:
        return ""
    said = ""
    if actions:
        said = (
            "\n\nTHE SCREENS' ACTIONS. Each screen's sections name what a person "
            "does there; these have no workflow launched from that screen yet. "
            "For each, author the workflow that does it — named as the action is, "
            "and with that screen's page id in `launchedFrom` — or leave it "
            "deliberately. They are the application's work: an order nobody can "
            "accept is not an order system. An action with `by` is done only by "
            "people of those roles, on a section only they see: the workflow is "
            "theirs to run, not everyone's who opens the screen.\n\n```json\n"
            + __import__("json").dumps(actions, indent=1) + "\n```")
    if not slots:
        return said.lstrip()
    return said.lstrip() + ("\n\n" if said else "") + (
        f"{len(slots)} page(s) in this application exist in order to submit "
        "something — a create page, or a list where its records are added "
        "(`addsHere`) — and none of them has a workflow to submit to. They are "
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
