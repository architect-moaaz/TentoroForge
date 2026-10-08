"""Who designs the screens — asked once, at the approval gate.

The design note is ``docs/plans/2026-09-13-ux-pilot-page-generation.md``. Smith
presents a two-option choice when the user approves a definition that has
pages and no answer yet: the Forge UI Designer (A2UI composing from the
component catalog) or UX Pilot (each page generated from its brief through
the organisation's UX Pilot MCP configuration).

Asked here rather than in the opening clarifier because the clarifier's
questions are worded by a model and answered in prose that becomes part of
the brief; this answer has to reach code (`page_layouts` dispatches on it),
so both the question and the recognition of its answer are fixed text. The
approval gate is also the right moment: it is the last thing the user says
before the build, and `page_layouts` runs in the build's seventh wave, four
waves after `page_contracts` has written the pages the agent prompts from.

WHAT EXISTS AT THE GATE IS REQUIREMENTS, NOT PAGES. The define run is two
nodes (`requirements`, `application_model`); the data model, pages and
workflows are authored by the build. The first version of this asked only
when pages existed, which at the gate is never — DC2 sat at BLUEPRINT_REVIEW
with 24 requirements and 0 pages and would have built without being asked.

Recorded twice, deliberately: ``application.uiDesigner`` is the fact the
executor reads, and a ``decisions`` row is the citable record of the user
having chosen (§20). The row is prose for people; the field is an enum for
code. They cannot drift because both are written in one call.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

logger = logging.getLogger(__name__)

FORGE = "forge"
UXPILOT = "uxpilot"

#: The card's two options, in the order they are shown. The first is the
#: default in every other sense too: what an unanswered application means.
OPTIONS: tuple[str, str] = ("Forge UI Designer", "UX Pilot")

#: The sentence that identifies the question in a transcript. `answer_in`
#: accepts an option only when the turn before it carried this.
_MARK = "Who should design the screens?"

#: The sentence that identifies the key request in a transcript, and the two ways a person can
#: answer it besides pasting a key: say it is saved, or take the Forge designer instead.
_KEY_MARK = "I need your UX Pilot API key"
KEY_SAVED = "UX Pilot key saved"
USE_FORGE_INSTEAD = "Use Forge UI Designer instead"

#: The field the chat shows for the key. Names the integration row the Settings page writes;
#: it never carries a value. The panel sends the typed key straight to that row, so the key is
#: stored encrypted with the organisation's other integrations and is never a chat message.
SECRET_FIELD: dict[str, str] = {
    "provider": "uxpilot",
    "key": "UXPILOT_API_KEY",
    "label": "UX Pilot API key",
    "placeholder": "ep_...",
    # What the panel says to continue once the key is stored: the words `key_saved_in` recognises.
    "saved": KEY_SAVED,
}

_ANSWERS: dict[str, str] = {
    "forge ui designer": FORGE, "forge": FORGE, "forge designer": FORGE,
    "ui designer": FORGE, "a2ui": FORGE,
    "ux pilot": UXPILOT, "uxpilot": UXPILOT, "ux-pilot": UXPILOT,
}

KEY_TEXT = (
    f"UX Pilot it is. {_KEY_MARK} before I can build. Paste it in the box below: it is saved, "
    "encrypted, with your organisation's other integrations (the same place as Settings → "
    "Integrations → UX Pilot), and it is never written into this conversation. You can also "
    "build with the Forge UI Designer instead."
)

#: Kept for callers that still import the old name.
CONFIGURE_TEXT = KEY_TEXT


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def live_pages(doc: dict) -> list[dict]:
    return [p for p in (doc.get("pages") or [])
            if isinstance(p, dict) and p.get("id") and p.get("status") != "DEPRECATED"]


def chosen(doc: dict) -> str:
    """``forge`` / ``uxpilot`` as recorded, or "" when nobody has been asked."""
    value = str(((doc or {}).get("application") or {}).get("uiDesigner") or "").strip()
    return value if value in (FORGE, UXPILOT) else ""


def _live(items: Any) -> list[dict]:
    return [x for x in (items or []) if isinstance(x, dict) and x.get("status") != "DEPRECATED"]


def undecided(doc: dict) -> bool:
    """Whether approving now should ask first: there is a definition to build
    (requirements, or pages on a re-approval of a built application) and no
    answer is on record. An empty document has nothing to ask about, and
    asking would stall an approval that builds nothing."""
    defined = bool(_live(doc.get("requirements")) or live_pages(doc))
    return defined and not chosen(doc)


def question(doc: dict) -> str:
    n = len(live_pages(doc))
    # Pages are usually not defined yet at the gate; the count is given only
    # when the build has already produced one.
    cost = (f"about 9 UX Pilot credits per screen ({n} screen{'s' if n != 1 else ''})"
            if n else "about 9 UX Pilot credits per screen")
    return (
        f"Your definition is approved. {_MARK}\n\n"
        f"- **Forge UI Designer:** every page composed from Forge's component "
        f"library. Consistent across pages, wired to your data by "
        f"construction, no extra cost.\n"
        f"- **UX Pilot:** one UX Pilot run draws every screen of the application "
        f"together, in one visual style, using your UX Pilot workspace and API "
        f"key. Each page is then written from its drawing, wired to your data. "
        f"Richer visuals; spends {cost}, once, and again only if a page's brief "
        f"changes."
    )


def is_question(text: str) -> bool:
    return _MARK in (text or "")


def answer_in(message: str, history: Iterable[tuple[str, str]]) -> str:
    """``forge`` / ``uxpilot`` when ``message`` answers the question Smith just
    asked, else "". The turn immediately before must be the question: the
    words "UX Pilot" in an unrelated message are not a decision."""
    turns = [(str(r or "").lower(), str(t or "")) for r, t in history if str(t or "").strip()]
    if not turns:
        return ""
    role, text = turns[-1]
    if role not in ("smith", "assistant"):
        return ""
    if is_key_prompt(text):
        return FORGE if _norm(message) == _norm(USE_FORGE_INSTEAD) else ""
    if not is_question(text):
        return ""
    return _ANSWERS.get(_norm(message), "")


def record(svc: Any, choice: str, *, reason: str = "Chosen at the approval gate.") -> str:
    """Write the choice to the application and a decision row; return what
    Smith says about it."""
    if choice not in (FORGE, UXPILOT):
        raise ValueError(f"not a designer: {choice!r}")
    svc.doc.setdefault("application", {})["uiDesigner"] = choice
    label = OPTIONS[0] if choice == FORGE else OPTIONS[1]
    text = f"{_DECISION_PREFIX} {label}."
    try:
        # The allocator needs the document's ids bound before a new row can
        # be keyed; the same step every other deterministic decision takes.
        from services.smith.smith import bootstrap as _bind_ids

        _bind_ids(svc)
        # A change of mind supersedes (§20, §92): the earlier row is retired
        # and the new one names it, so the history reads as a decision that
        # changed rather than as two that never met. The same answer twice
        # is one row. Found by its text because a decision row has no field
        # naming its subject and the allocator re-keys unbound rows on
        # every bootstrap.
        current = _current_row(svc.doc)
        if current is not None and current.get("decision") == text:
            pass
        else:
            body = {
                "decision": text,
                "reason": reason,
                "source": "user",
                "approvedBy": "user",
                "binding": True,
                "status": "APPROVED",
                "version": svc.doc.get("version", 1),
            }
            if current is not None:
                body["supersedes"] = current["id"]
                current["status"] = "DEPRECATED"
            svc.upsert("decisions", body, natural_key=f"ui-designer-{choice}")
    except Exception as exc:  # noqa: BLE001 — the fact is written; the citation is a courtesy
        logger.warning("[ui-designer] decision row not recorded: %s", exc)
    svc.validate()
    svc.save()
    if choice == FORGE:
        return "Forge UI Designer it is. Building now."
    return ("UX Pilot it is: one run will draw every screen from the definition, and each page "
            "is written from its drawing. Building now.")


_DECISION_PREFIX = "Screens are designed by"


def _current_row(doc: dict) -> dict | None:
    """The live decision about the designer, if one was recorded."""
    for d in doc.get("decisions") or []:
        if (isinstance(d, dict) and d.get("id")
                and str(d.get("decision") or "").startswith(_DECISION_PREFIX)
                and d.get("status") != "DEPRECATED"):
            return d
    return None


def configured(output_dir: Any) -> bool:
    from services.uxpilot.generate import configured as _configured

    return _configured(output_dir)


def is_key_prompt(text: str) -> bool:
    return _KEY_MARK in (text or "")


def key_prompt() -> dict[str, Any]:
    """The message that asks for the key: the field to type it in, and a way out."""
    return {"text": KEY_TEXT, "options": [USE_FORGE_INSTEAD], "secret": dict(SECRET_FIELD),
            "status": "asked"}


def _platform_default() -> bool:
    """An operator who set `FORGE_UI_DESIGNER` has decided for every application on the platform."""
    import os

    return os.environ.get("FORGE_UI_DESIGNER", "").strip().lower() in (FORGE, UXPILOT)


def gate(doc: dict, output_dir: Any) -> dict[str, Any] | None:
    """The message to show INSTEAD of starting the build, or None when it may start.

    Two reasons to stop, in order: nobody has said who designs the screens, and UX Pilot was
    chosen but there is no key to use it with."""
    if undecided(doc) and not _platform_default():
        return {"text": question(doc), "options": list(OPTIONS), "status": "asked"}
    if chosen(doc) == UXPILOT and not configured(output_dir):
        return key_prompt()
    return None


def key_saved_in(message: str, history: Iterable[tuple[str, str]]) -> bool:
    """Whether ``message`` is the panel saying the key was saved, in answer to the key request."""
    turns = [(str(r or "").lower(), str(t or "")) for r, t in history if str(t or "").strip()]
    if not turns:
        return False
    role, text = turns[-1]
    return role in ("smith", "assistant") and is_key_prompt(text) and _norm(message) == _norm(KEY_SAVED)
